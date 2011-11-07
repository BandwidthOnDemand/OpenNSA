"""
OpenNSA JunOS backend.
"""

# configure snippet:

# opennsa@cph> configure <return>
# Entering configuration mode
#
#[edit]
#
#opennsa@cph# set protocols connections interface-switch ps-to-netherlight-1780 interface ge-1/0/5.1780
#
#[edit]
#
#opennsa@cph# set interfaces ge-1/0/5 unit 1780 vlan-id 1780 encapsulation vlan-ccc
#
#[edit]
#opennsa@cph# delete interfaces ge-1/0/5 unit 1780
#
#[edit]
#opennsa@cph# delete protocols connections interface-switch ps-to-netherlight-1780
#
#[edit]
#
# Basically stuff should end with [edit] :-)
#

import StringIO

from twisted.python import log
from twisted.internet import defer, protocol, reactor, endpoints
from twisted.conch import error
from twisted.conch.ssh import common, transport, keys, userauth, connection, channel

from opennsa import state
from opennsa.backends.common import calendar as reservationcalendar



# Stuff to get from config:
JUNOS_HOST              = 'cph.dcn.nordu.net'
JUNOS_HOST_PORT         = 22
JUNOS_HOST_FINGERPRINT  = 'd8:43:73:ee:a4:87:87:36:3f:c4:e5:3e:7c:d9:8b:d7'

USERNAME                = 'opennsa'
PUBLIC_KEY_PATH         = '/home/opennsa/.ssh/id_rsa.pub'
PRIVATE_KEY_PATH        = '/home/opennsa/.ssh/id_rsa'

#> set protocols connections interface-switch ps-to-netherlight-1780 interface ge-1/0/5.1780
#> set protocols connections interface-switch ps-to-netherlight-1780 interface ge-1/1/9.1780
#> set interfaces ge-1/0/5 unit 1780 vlan-id 1780 encapsulation vlan-ccc
#> set interfaces ge-1/1/9 unit 1780 vlan-id 1780 encapsulation vlan-ccc

# parameterized commands
COMMAND_CONFIGURE           = 'configure'
COMMAND_SET_CONNECTIONS     = 'set protocols connections interface-switch %(name)s interface %(interface)s' # connection name / interface
COMMAND_SET_INTERFACES      = 'set interfaces %(port)s unit %(vlan)s vlan-id %(vlan)s encapsulation vlan-ccc' # port / vlan / vlan
COMMAND_DELETE_INTERFACES   = 'delete interfaces %(port)s unit %(vlan)s' # port / vlan
COMMAND_DELETE_CONNECTIONS  = 'delete protocols connections interface-switch %(name)s' # name

LOG_SYSTEM = 'opennsa.JunOS'

PORT_MAPPING = {
    'ams-80'    : 'ge-1/0/5.1780',
    'ams-81'    : 'ge-1/0/5.1781',
    'ams-82'    : 'ge-1/0/5.1782',
    'ams-83'    : 'ge-1/0/5.1783',
    'ps-80'     : 'ge-1/1/9.1780',
    'ps-81'     : 'ge-1/1/9.1781',
    'ps-82'     : 'ge-1/1/9.1782',
    'ps-83'     : 'ge-1/1/9.1783'
}

NAME_PREFIX = 'ps-to-netherlight-'


def portToInterfaceVLAN(topo_port):

    interface = PORT_MAPPING[topo_port]
    port, vlan = interface.split('.')
    connection_name = NAME_PREFIX + vlan
    return connection_name, interface, port, vlan


def createConfigureCommands(source_port, dest_port):

    s_connection_name, s_interface, s_port, s_vlan = portToInterfaceVLAN(source_port)
    d_connection_name, d_interface, d_port, d_vlan = portToInterfaceVLAN(dest_port)

    assert s_vlan == d_vlan, 'Source and destination VLANs differ, unpossible!'

    cfg_conn_source = COMMAND_SET_CONNECTIONS % {'name':s_connection_name, 'interface':s_interface }
    cfg_conn_dest   = COMMAND_SET_CONNECTIONS % {'name':d_connection_name, 'interface':d_interface }
    cfg_intf_source = COMMAND_SET_INTERFACES  % {'port':s_port, 'vlan': s_vlan }
    cfg_intf_dest   = COMMAND_SET_INTERFACES  % {'port':d_port, 'vlan': d_vlan }

    commands = [ cfg_conn_source, cfg_conn_dest, cfg_intf_source, cfg_intf_dest ]
    return commands


def createDeleteCommands(source_port, dest_port):

    s_connection_name, s_interface, s_port, s_vlan = portToInterfaceVLAN(source_port)
    d_connection_name, d_interface, d_port, d_vlan = portToInterfaceVLAN(dest_port)

    assert s_vlan == d_vlan, 'Source and destination VLANs differ, unpossible!'

    del_intf_source = COMMAND_DELETE_INTERFACES  % {'port':s_port, 'vlan': s_vlan }
    del_intf_dest   = COMMAND_DELETE_INTERFACES  % {'port':d_port, 'vlan': d_vlan }
    del_conn        = COMMAND_DELETE_CONNECTIONS % {'name':s_connection_name }

    commands = [ del_intf_source, del_intf_dest, del_conn ]
    return commands


# ----


class SSHClientTransport(transport.SSHClientTransport):

    def __init__(self, fingerprints=None):
        self.fingerprints = fingerprints or []
        self.secure_defer = defer.Deferred()


    def verifyHostKey(self, public_key, fingerprint):
        if fingerprint in self.fingerprints:
            return defer.succeed(1)
        else:
            return defer.fail(error.ConchError('Fingerprint not accepted'))


    def connectionSecure(self):
        self.secure_defer.callback(self)



class SSHClientFactory(protocol.ClientFactory):

    protocol = SSHClientTransport

    def __init__(self, fingerprints=None):
        # ClientFactory has no __init__ method, so we don't call it
        self.fingerprints = fingerprints or []


    def buildProtocol(self, addr):

        p = self.protocol(self.fingerprints)
        p.factory = self
        return p



class ClientUserAuth(userauth.SSHUserAuthClient):

    def __init__(self, user, connection, public_key_path, private_key_path):
        userauth.SSHUserAuthClient.__init__(self, user, connection)
        self.public_key_path    = public_key_path
        self.private_key_path   = private_key_path

    def getPassword(self, prompt = None):
        return # this says we won't do password authentication

    def getPublicKey(self):
        return keys.Key.fromFile(self.public_key_path)

    def getPrivateKey(self):
        return defer.succeed( keys.Key.fromFile(self.private_key_path) )



class SSHConnection(connection.SSHConnection):

    def __init__(self):
        connection.SSHConnection.__init__(self)
        self.service_started = defer.Deferred()

    def serviceStarted(self):
        self.service_started.callback(self)



class SSHChannel(channel.SSHChannel):

    name = 'session'

    def __init__(self, localWindow = 0, localMaxPacket = 0, remoteWindow = 0, remoteMaxPacket = 0, conn = None, data=None, avatar = None):
        channel.SSHChannel.__init__(self, localWindow = 0, localMaxPacket = 0, remoteWindow = 0, remoteMaxPacket = 0, conn = None, data=None, avatar = None)
        self.channel_open = defer.Deferred()

        self.line = ''

        self.wait_defer = None
        self.wait_line  = None

    def channelOpen(self, data):
        self.channel_open.callback(self)
        #print "CHANNEL OPEN"


    @defer.inlineCallbacks
    def sendCommands(self, commands):
        LT = '\r' # line termination
        log.msg('sendCommands', system=LOG_SYSTEM)

        try:
            yield self.conn.sendRequest(self, 'shell', '', wantReply=1)

            d = self.waitForLine('[edit]')
            self.write('configure' + LT)
            yield d

            log.msg('Entered configure mode', system=LOG_SYSTEM)

            for cmd in commands:
                log.msg('CMD> %s' % cmd, system=LOG_SYSTEM)
                d = self.waitForLine('[edit]')
                self.write(cmd + LT)
                yield d

            # commit commands, check for 'commit complete' as success
            # not quite sure how to handle failure here

#            # test stuff
#            d = self.waitForLine('[edit]')
#            self.write('commit check' + LT)

            d = self.waitForLine('commit complete')
            self.write('commit' + LT)
            yield d

        except Exception, e:
            log.msg('Error sending commands: %s' % str(e))
            raise e

        log.msg('Commands successfully sent', system=LOG_SYSTEM)
        self.sendEOF()
        self.closeIt()


    def request_exit_status(self, data):
        if data and len(data) != 4:
            log.msg('Exit status data: %s' % data, system=LOG_SYSTEM)

    def waitForLine(self, line):
        self.wait_line = line
        self.wait_defer = defer.Deferred()
        return self.wait_defer


    def matchLine(self, line):
        if self.wait_line and self.wait_defer:
            if self.wait_line == line.strip():
                d = self.wait_defer
                self.wait_line  = None
                self.wait_defer = None
                d.callback(self)
            else:
                pass


    def sendEOF(self, passthru=None):
        self.conn.sendEOF(self)
        return passthru


    def closeIt(self, passthru=None):
        self.loseConnection()
        return passthru


    def dataReceived(self, data):
        if len(data) == 0:
            pass
        else:
            self.line += data
            if '\n' in data:
                lines = [ line.strip() for line in self.line.split('\n') if line.strip() ]
                self.line = ''
                for l in lines:
                    self.matchLine(l)




class JunOSCommandSender:


    def __init__(self):
        self.client = None
        self.proto  = None


    def createSSHConnection(self):

        def transportSecure(client, proto):
            return proto

        def gotProtocol(proto):
            proto.secure_defer.addCallback(transportSecure, proto)
            return proto.secure_defer

        # should check if there is an existing protocol in place
        if self.proto:
            log.msg('Reusing SSH connection', system=LOG_SYSTEM)
            return defer.succeed(self.proto)

        factory = SSHClientFactory( [ JUNOS_HOST_FINGERPRINT ] )
        point = endpoints.TCP4ClientEndpoint(reactor, JUNOS_HOST, JUNOS_HOST_PORT)
        d = point.connect(factory)
        d.addCallback(gotProtocol)
        return d


    def getSSHChannel(self):

        def serviceStarted(connection):
            channel = SSHChannel(conn = connection)
            connection.openChannel(channel)
            return channel.channel_open

        def gotProtocol(proto):
            ssh_connection = SSHConnection()
            proto.requestService(ClientUserAuth(USERNAME, ssh_connection, PUBLIC_KEY_PATH, PRIVATE_KEY_PATH))
            ssh_connection.service_started.addCallback(serviceStarted)
            return ssh_connection.service_started

        d = self.createSSHConnection()
        d.addCallback(gotProtocol)
        return d


    def provision(self, source_port, dest_port, start_time, end_time):

        commands = createConfigureCommands(source_port, dest_port)

        def gotChannel(channel):
            d = channel.sendCommands(commands)
            return d

        d = self.getSSHChannel()
        d.addCallback(gotChannel)
        return d


    def release(self, source_port, dest_port, start_time, end_time):

        commands = createDeleteCommands(source_port, dest_port)

        def gotChannel(channel):
            d = channel.sendCommands(commands)
            return d

        d = self.getSSHChannel()
        d.addCallback(gotChannel)
        return d


# --------


class JunOSBackend:

    def __init__(self, network_name):
        self.network_name = network_name
        self.command_sender = JunOSCommandSender()
        self.calendar = reservationcalendar.ReservationCalendar()


    def createConnection(self, source_port, dest_port, service_parameters):

        # probably need a short hand for this
        self.calendar.checkReservation(source_port, service_parameters.start_time, service_parameters.end_time)
        self.calendar.checkReservation(dest_port  , service_parameters.start_time, service_parameters.end_time)

        self.calendar.addConnection(source_port, service_parameters.start_time, service_parameters.end_time)
        self.calendar.addConnection(dest_port  , service_parameters.start_time, service_parameters.end_time)

        c = JunOSConnection(source_port, dest_port, service_parameters, self.command_sender, self.calendar)
        return c



class JunOSConnection:

    def __init__(self, source_port, dest_port, service_parameters, command_sender, calendar):
        self.source_port = source_port
        self.dest_port = dest_port
        self.service_parameters = service_parameters
        self.command_sender = command_sender
        self.calendar = calendar

        self.state = state.ConnectionState()



    def stps(self):
        return self.service_parameters.source_stp, self.service_parameters.dest_stp


    def reserve(self):
        # resource availability has already been checked in the backend during connection creation
        # since we assume no other NRM for this backend (OpenNSA have exclusive rights to the HW) there is nothing to do here
        self.state.switchState(state.RESERVING)

        self.state.switchState(state.RESERVED)

        # state transition to SCHEDULED should be added sometime
        return defer.succeed(self)


    def provision(self):

        def provisioned(_):
            self.state.switchState(state.PROVISIONED)
            return self

        # start the hardware, we'll worry about scheduling later
        self.state.switchState(state.PROVISIONING)
        d = self.command_sender.provision(self.source_port, self.dest_port, self.service_parameters.start_time, self.service_parameters.end_time)
        d.addCallback(provisioned)
        return d


    def release(self):

        def released(_):
            self.state.switchState(state.RESERVED)
            return self

        self.state.switchState(state.RELEASING)

        d = self.command_sender.release(self.source_port, self.dest_port, self.service_parameters.start_time, self.service_parameters.end_time)
        d.addCallback(released)
        return d


    def terminate(self):

        self.state.switchState(state.TERMINATING)

        self.calendar.removeConnection(self.source_port, self.service_parameters.start_time, self.service_parameters.end_time)
        self.calendar.removeConnection(self.dest_port  , self.service_parameters.start_time, self.service_parameters.end_time)

        self.state.switchState(state.TERMINATED)

        return defer.succeed(self)


