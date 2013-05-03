"""
Generic backend for deployments where OpenNSA is the only NRM (i.e. there is no
other system for interacting with the hardware).

Using this module, such a backend will only have to supply functionality for
setting up and tearing down links and does not have to deal state management.

The use this module a connection manager has to be supplied. The methods
setupLink(source_port, dest_port) and tearDown(source_port, dest_port) must be
implemented in the manager. The methods should return a deferred.

Author: Henrik Thostrup Jensen <htj@nordu.net>
Copyright: NORDUnet (2011-2012)
"""

import random
import datetime

from dateutil.tz import tzutc

from twisted.python import log
from twisted.internet import reactor, defer
from twisted.application import service

from opennsa import error, state, nsa, database
from opennsa.backends.common import scheduler, calendar

from twistar.dbobject import DBObject



class Simplebackendconnection(DBObject):
    pass



class SimpleBackend(service.Service):

    def __init__(self, network, connection_manager, log_system):

        self.network = network
        self.connection_manager = connection_manager
        self.log_system = log_system

        self.scheduler = scheduler.CallScheduler()
        self.calendar  = calendar.ReservationCalendar()
        # need to build the calendar as well

        # the connection cache is a work-around for a race condition in mmm... something
        self.connection_cache = {}

        # need to build schedule here
        self.restore_defer = defer.Deferred()
        reactor.callWhenRunning(self.buildSchedule)


    def stopService(self):
        service.Service.stopService(self)
        return self.restore_defer.addCallback( lambda _ : self.scheduler.cancelAllCalls() )


    @defer.inlineCallbacks
    def buildSchedule(self):

        conns = yield Simplebackendconnection.find(where=['lifecycle_state <> ?', state.TERMINATED])
        for conn in conns:
            # avoid race with newly created connections
            if self.scheduler.hasScheduledCall(conn.connection_id):
                continue

            now = datetime.datetime.utcnow()

            if conn.end_time < now and conn.lifecycle_state != state.TERMINATED:
                yield self._doTerminate(conn)

            elif conn.start_time < now:
                if conn.provision_state == state.PROVISIONED:
                    self.scheduler.scheduleCall(conn.connection_id, conn.end_time, self._doActivate, conn)
                    log.msg('Transition scheduled for %s: terminate at %s.' % (conn.connection_id, conn.end_time), system=self.log_system)
                elif conn.provision_state == state.SCHEDULED:
                    self.scheduler.scheduleCall(conn.connection_id, conn.end_time, self._doTerminate, conn)
                    log.msg('Transition scheduled for %s: terminate at %s.' % (conn.connection_id, conn.end_time), system=self.log_system)
                else:
                    log.msg('Unhandled provision state %s for connection %s in scheduler building' % (conn.provision_state, conn.connection_id))

            elif conn.start_time > now:
                if conn.provision_state == state.PROVISIONED:
                    yield self._doActivate(conn)
                elif conn.provision_state == state.SCHEDULED:
                    self.scheduler.scheduleCall(conn.connection_id, conn.end_time, self._doTerminate, conn)
                    log.msg('Transition scheduled for %s: terminate at %s.' % (conn.connection_id, conn.end_time), system=self.log_system)
                else:
                    log.msg('Unhandled provision state %s for connection %s in scheduler building' % (conn.provision_state, conn.connection_id))

            else:
                log.msg('Unhandled start/end time configuration for connection %s' % conn.connection_id)

        self.restore_defer.callback(None)



    @defer.inlineCallbacks
    def _getConnection(self, connection_id, requester_nsa):
        # add security check sometime
        try:
            defer.returnValue(self.connection_cache[connection_id])
        except KeyError:
            pass
        conns = yield Simplebackendconnection.findBy(connection_id=connection_id)
        if len(conns) == 0:
            raise error.ConnectionNonExistentError('No connection with id %s' % connection_id)
        self.connection_cache[connection_id] = conns[0]
        defer.returnValue( conns[0] ) # we only get one, unique in db


    def logStateUpdate(self, conn, state_msg):
        log.msg('Link: %s, %s -> %s : %s.' % (conn.connection_id, conn.source_port, conn.dest_port, state_msg), system=self.log_system)


    @defer.inlineCallbacks
    def reserve(self, requester_nsa, provider_nsa, session_security_attr, global_reservation_id, description, connection_id, service_params):

        # return defer.fail( error.InternalNRMError('test reservation failure') )

        # should perhaps verify nsa, but not that important

        if connection_id:
            raise ValueError('Cannot handle cases with existing connection id (yet)')
            #conns = yield Simplebackendconnection.findBy(connection_id=connection_id)

        # need to check schedule

        #connection_id = str(uuid.uuid1())
        connection_id = str(random.randint(100000,999999))

        source_stp = service_params.source_stp
        dest_stp   = service_params.dest_stp

        # resolve nrm ports from the topology

        if len(source_stp.labels) == 0:
            raise error.TopologyError('Source STP must specify a label')
        if len(dest_stp.labels) == 0:
            raise error.TopologyError('Destination STP must specify a label')

        if len(source_stp.labels) > 1:
            raise error.TopologyError('Source STP specifies more than one label. Only one label is currently supported')
        if len(dest_stp.labels) > 1:
            raise error.TopologyError('Destination STP specifies more than one label. Only one label is currently supported')

#        # choose a label to use :-)
#        src_label_value = str( source_stp.labels[0].randomLabel() )
#        dst_label_value = str( dest_stp.labels[0].randomLabel() )

        src_label_candidate = source_stp.labels[0]
        dst_label_candidate = dest_stp.labels[0]
        assert src_label_candidate.type_ == dst_label_candidate.type_, 'Cannot connect ports with different label types'

        # do the: lets find the labels danace
        if self.connection_manager.canSwapLabel(src_label_candidate.type_):
            for lv in src_label_candidate.enumerateValues():
                src_resource = self.connection_manager.getResource(source_stp.port, src_label_candidate.type_, lv)
                try:
                    self.calendar.checkReservation(src_resource, service_params.start_time, service_params.end_time)
                    self.calendar.addConnection(   src_resource, service_params.start_time, service_params.end_time)
                    src_label = nsa.Label(src_label_candidate.type_, str(lv))
                    break
                except error.STPUnavailableError:
                    continue
                raise error.STPUnavailableError('STP %s not available in specified time span' % source_stp)


            for lv in dst_label_candidate.enumerateValues():
                dst_resource = self.connection_manager.getResource(dest_stp.port, dst_label_candidate.type_, lv)
                try:
                    self.calendar.checkReservation(dst_resource, service_params.start_time, service_params.end_time)
                    self.calendar.addConnection(   dst_resource, service_params.start_time, service_params.end_time)
                    dst_label = nsa.Label(dst_label_candidate.type_, str(lv))
                    break
                except error.STPUnavailableError:
                    continue
                raise error.STPUnavailableError('STP %s not available in specified time span' % dest_stp)

        else:
            label_candidate = src_label_candidate.intersect(dst_label_candidate)

            for lv in label_candidate.enumerateValues():
                src_resource = self.connection_manager.getResource(source_stp.port, label_candidate.type_, lv)
                dst_resource = self.connection_manager.getResource(dest_stp.port,   label_candidate.type_, lv)
                try:
                    self.calendar.checkReservation(src_resource, service_params.start_time, service_params.end_time)
                    self.calendar.checkReservation(dst_resource, service_params.start_time, service_params.end_time)
                    self.calendar.addConnection(   src_resource, service_params.start_time, service_params.end_time)
                    self.calendar.addConnection(   dst_resource, service_params.start_time, service_params.end_time)
                    src_label = nsa.Label(label_candidate.type_, str(lv))
                    dst_label = nsa.Label(label_candidate.type_, str(lv))
                    break
                except error.STPUnavailableError:
                    continue
                raise error.STPUnavailableError('STP combination %s and %s not available in specified time span' % dest_stp)

#        nrm_src_port = self.topology.getNetwork(self.network).getInterface(link.src_port) + '.' + src_label_value
#        nrm_dst_port = self.topology.getNetwork(self.network).getInterface(link.dst_port) + '.' + dst_label_value

        conn = Simplebackendconnection(connection_id=connection_id, revision=0, global_reservation_id=global_reservation_id, description=description, nsa=provider_nsa,
                                       reserve_time=datetime.datetime.utcnow(),
                                       reservation_state=state.INITIAL, provision_state=state.SCHEDULED, activation_state=state.INACTIVE, lifecycle_state=state.INITIAL,
                                       source_network=source_stp.network, source_port=source_stp.port, source_labels=[src_label],
                                       dest_network=dest_stp.network, dest_port=dest_stp.port, dest_labels=[dst_label],
                                       start_time=service_params.start_time, end_time=service_params.end_time,
                                       bandwidth=service_params.bandwidth)
        yield conn.save()


        state.reserving(conn)
        self.logStateUpdate(conn, 'RESERVING')
        state.reserved(conn)
        self.logStateUpdate(conn, 'RESERVED')
        # need to schedule 2PC timeout

        self.scheduler.scheduleCall(connection_id, conn.end_time, self._doTerminate, conn)
        log.msg('Transition scheduled for %s: terminate at %s.' % (connection_id, conn.end_time), system=self.log_system)


        sc_source_stp = nsa.STP(source_stp.network, source_stp.port, labels=[src_label])
        sc_dest_stp   = nsa.STP(dest_stp.network,   dest_stp.port,   labels=[dst_label])
        sp = nsa.ServiceParameters(service_params.start_time, service_params.end_time, sc_source_stp, sc_dest_stp, service_params.bandwidth)
        rig = (global_reservation_id, description, connection_id, sp)
        defer.returnValue(rig)


    @defer.inlineCallbacks
    def provision(self, requester_nsa, provider_nsa, session_security_attr, connection_id):


        conn = yield self._getConnection(connection_id, requester_nsa)

        now = datetime.datetime.utcnow()
        if conn.end_time <= now:
            raise error.ConnectionGone('Cannot provision connection after end time (end time: %s, current time: %s).' % (conn.end_time, now))

        yield state.provisioning(conn)
        self.logStateUpdate(conn, 'PROVISIONING')

        self.scheduler.cancelCall(connection_id)

        if conn.start_time <= now:
            d = _doActivate(conn)
        else:
            self.scheduler.scheduleCall(connection_id, conn.start_time, self._doActivate, conn)
            log.msg('Transition scheduled for %s: activate at %s.' % (connection_id, conn.start_time), system=self.log_system)

        yield state.provisioned(conn)
        self.logStateUpdate(conn, 'PROVISIONED')
        defer.returnValue(conn.connection_id)


    @defer.inlineCallbacks
    def release(self, requester_nsa, provider_nsa, session_security_attr, connection_id):

        conn = yield self._getConnection(connection_id, requester_nsa)

        yield state.releasing(conn)
        self.logStateUpdate(conn, 'RELEASING')

        self.scheduler.cancelCall(connection_id)

        if conn.activation_state == state.ACTIVE:
            yield state.deactivating(conn)
            self.logStateUpdate(conn, state.DEACTIVATING)
            try:
                yield self.connection_manager.teardownLink(self.source_port, self.dest_port)
                yield state.inactive(conn)
            except Exception as e:
                log.msg('Error terminating connection: %s' % r.getErrorMessage())

        self.scheduler.scheduleCall(connection_id, conn.end_time, self._doTerminate, conn)
        log.msg('Transition scheduled for %s: terminating at %s.' % (connection_id, conn.end_time), system=self.log_system)

        yield state.scheduled(conn)
        self.logStateUpdate(conn, 'RELEASED')
        defer.returnValue(conn.connection_id)


    @defer.inlineCallbacks
    def terminate(self, requester_nsa, provider_nsa, session_security_attr, connection_id):
        # return defer.fail( error.InternalNRMError('test termination failure') )

        conn = yield self._getConnection(connection_id, requester_nsa)
        yield self._doTerminate(conn)


    def query(self, query_filter):
        pass



    @defer.inlineCallbacks
    def _doActivate(conn):
        yield state.activating(conn)
        self.logStateUpdate(conn, 'ACTIVATING')
        try:
            yield self.connection_manager.setupLink(conn.source_port, conn.dest_port)
            self.scheduler.scheduleCall(connection_id, conn.end_time, self._doTerminate, conn)
            log.msg('Transition scheduled for %s: activating at %s.' % (connection_id, conn.start_time), system=self.log_system)
            yield state.active(conn)
            self.logStateUpdate(conn, 'ACTIVE')
        except Exception, e:
            log.msg('Error setting up connection: %s' % e)
            yield state.inactive(conn)
            self.logStateUpdate(conn, 'INACTIVE')
            raise e


    @defer.inlineCallbacks
    def _doTerminate(self, conn):

        if conn.lifecycle_state == state.TERMINATED:
            defer.returnValue(conn.cid)

        yield state.terminating(conn)
        self.logStateUpdate(conn, state.TERMINATING)

        self.scheduler.cancelCall(conn.connection_id)

        if conn.activation_state == state.ACTIVE:
            yield state.deactivating(conn)
            self.logStateUpdate(conn, state.DEACTIVATING)
            try:
                yield self.connection_manager.teardownLink(self.source_port, self.dest_port)
                yield state.inactive(conn)
                # we can only remove resource reservation entry if we succesfully shut down the link :-(
                self.calendar.removeConnection(self.source_port, self.service_parameters.start_time, self.service_parameters.end_time)
                self.calendar.removeConnection(self.dest_port  , self.service_parameters.start_time, self.service_parameters.end_time)
            except Exception as e:
                log.msg('Error terminating connection: %s' % r.getErrorMessage())

        yield state.terminated(conn)
        self.logStateUpdate(conn, 'TERMINATED')
        defer.returnValue(conn.connection_id)

