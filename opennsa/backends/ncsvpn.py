"""
Backend for NCS VPN module.

Author: Henrik Thostrup Jensen <htj at nordu.net>
Copyright: NORDUnet(2011-2013)
"""

import base64
import random

from twisted.python import log

from opennsa import constants as cnt, config
from opennsa.backends.common import genericbackend
from opennsa.protocols.shared import httpclient


# basic payload
#
#<service xmlns="http://tail-f.com/ns/ncs" >
#  <object-id>nsi-vpn</object-id>
#  <type>
#    <vpn xmlns="http://nordu.net/ns/ncs/vpn">
#      <side-a>
#        <router>routerA</router>
#        <interface>interface1</interface>
#      </side-a>
#      <side-b>
#        <router></router>
#        <interface>ge-1/0/1</interface>
#      </side-b>
#      <vlan>1720</vlan>
#    </vpn>
#  </type>
#</service>
#
# encapsulation type can be ethernet or ethernet-vlan
# vlan must be specified if encapsulation-type is ethernet-vlan, otherwise not
#
# the payload must be posted to the services url, e.g.,:
# http://localhost:8080/api/running/services
#
# To tear down the VPN, do a DELETE against
# "http://localhost:8080/api/running/services/service/nsi-vpn"
#
# The connection id -> object-id mapping is hence rather important to remember, but it can be the


ETHERNET_VPN_PAYLOAD_BASE = """
<service xmlns="http://tail-f.com/ns/ncs" >
  <object-id>%(service_name)s</object-id>
  <type>
    <vpn xmlns="http://nordu.net/ns/ncs/vpn">
      <side-a>
        <router>%(router_a)s</router>
        <interface>%(interface_a)s</interface>
      </side-a>
      <side-b>
        <router>%(router_b)s</router>
        <interface>%(interface_b)s</interface>
      </side-b>
    </vpn>
  </type>
</service>
"""

ETHERNET_VLAN_VPN_PAYLOAD_BASE = """
<service xmlns="http://tail-f.com/ns/ncs" >
  <object-id>%(service_name)s</object-id>
  <type>
    <vpn xmlns="http://nordu.net/ns/ncs/vpn">
      <side-a>
        <router>%(router_a)s</router>
        <interface>%(interface_a)s</interface>
      </side-a>
      <side-b>
        <router>%(router_b)s</router>
        <interface>%(interface_b)s</interface>
      </side-b>
      <vlan>%(vlan)i</vlan>
    </vpn>
  </type>
</service>
"""



LOG_SYSTEM = 'opennsa.ncsvpn'



class NCSVPNTarget(object):

    def __init__(self, router, interface, vlan=None):
        self.router = router
        self.interface = interface
        self.vlan = vlan

    def __str__(self):
        if self.vlan:
            return '<NCSVPNTarget %s/%s#%i>' % (self.router, self.interface, self.vlan)
        else:
            return '<NCSVPNTarget %s/%s>' % (self.router, self.interface)



def createVPNPayload(service_name, source_target, dest_target):

    intps = {
        'service_name'  : service_name,
        'router_a'      : source_target.router,
        'interface_a'   : source_target.interface,
        'router_b'      : dest_target.router,
        'interface_b'   : dest_target.interface
    }

    if source_target.vlan and dest_target.vlan:
        assert source_target.vlan == dest_target.vlan, 'VLANs must match (until we get rewrite in place)'
        intps['vlan'] = source_target.vlan
        payload = ETHERNET_VLAN_VPN_PAYLOAD_BASE % intps
    else:
        payload = ETHERNET_VPN_PAYLOAD_BASE % intps

    return payload



class NCSVPNConnectionManager:

    def __init__(self, ncs_services_url, user, password, port_map, log_system):
        self.ncs_services_url = ncs_services_url
        self.user             = user
        self.password         = password
        self.port_map         = port_map
        self.log_system       = log_system


    def getResource(self, port, label_type, label_value):
        assert label_type in (None, cnt.ETHERNET_VLAN), 'Label must be None or VLAN'
        return port # this contains router and port


    def getTarget(self, port, label_type, label_value):
        assert label_type in (None, cnt.ETHERNET_VLAN), 'Label must be None or VLAN'
        if label_type == cnt.ETHERNET_VLAN:
            vlan = int(label_value)
            assert 1 <= vlan <= 4095, 'Invalid label value for vlan: %s' % label_value

        ri = self.port_map[port]
        router, interface = ri.split(':')
        return NCSVPNTarget(router, interface, vlan)


    def createConnectionId(self, source_target, dest_target):
        return 'ON-' + str(random.randint(100000,999999))


    def canSwapLabel(self, label_type):
        return False # not yet
        #return label_type == cnt.ETHERNET_VLAN:


    def _createAuthzHeader(self):
        return 'Basic ' + base64.b64encode( self.user + ':' + self.password)


    def _createHeaders(self):
        headers = {}
        headers['Content-Type'] = 'application/vnd.yang.data+xml'
        headers['Authorization'] = self._createAuthzHeader()
        return headers

    def setupLink(self, connection_id, source_target, dest_target, bandwidth):
        payload = createVPNPayload(connection_id, source_target, dest_target)
        headers = self._createHeaders()

        def linkUp(_):
            log.msg('Link %s -> %s up' % (source_target, dest_target), system=self.log_system)

        d = httpclient.httpRequest(self.ncs_services_url, payload, headers, method='POST')
        d.addCallback(linkUp)
        return d


    def teardownLink(self, connection_id, source_target, dest_target, bandwidth):
        service_url = self.ncs_services_url + '/service/' + connection_id
        headers = self._createHeaders()

        def linkDown(_):
            log.msg('Link %s -> %s down' % (source_target, dest_target), system=self.log_system)

        d = httpclient.httpRequest(service_url, None, headers, method='DELETE')
        d.addCallback(linkDown)
        return d



def NCSVPNBackend(network_name, network_topology, parent_requester, port_map, cfg): 

    name = 'NCS VPN %s' % network_name

    # extract config items
    ncs_services_url = str(cfg[config.NCS_SERVICES_URL]) # convert from unicode
    user             = cfg[config.NCS_USER]
    password         = cfg[config.NCS_PASSWORD]

    cm = NCSVPNConnectionManager(ncs_services_url, user, password, port_map, name)
    return genericbackend.GenericBackend(network_name, network_topology, cm, parent_requester, name)

