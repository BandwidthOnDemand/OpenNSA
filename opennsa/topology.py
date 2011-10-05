"""
OpenNSA topology database and parser.

Author: Henrik Thostrup Jensen <htj@nordu.net>

Copyright: NORDUnet (2011)
"""

import json
import StringIO
from xml.etree import ElementTree as ET

from opennsa import nsa, error


# Constants for parsing GOLE topology format
OWL_NS  = 'http://www.w3.org/2002/07/owl#'
RDF_NS  = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'

GLIF_PREFIX = 'http://www.glif.is/working-groups/tech/dtox#'

NAMED_INDIVIDUAL        = ET.QName('{%s}NamedIndividual' % OWL_NS)
RDF_ABOUT               = ET.QName('{%s}about' % RDF_NS)
RDF_TYPE                = ET.QName('{%s}type' % RDF_NS)
RDF_RESOURCE            = ET.QName('{%s}resource' % RDF_NS)

GLIF_HAS_STP            = ET.QName('{%s}hasSTP' % GLIF_PREFIX)
GLIF_CONNECTED_TO       = ET.QName('{%s}connectedTo' % GLIF_PREFIX)
GLIF_MAX_CAPACITY       = ET.QName('{%s}maxCapacity' % GLIF_PREFIX)
GLIF_AVAILABLE_CAPACITY = ET.QName('{%s}availableCapacity' % GLIF_PREFIX)
GLIF_MANAGED_BY         = ET.QName('{%s}managedBy' % GLIF_PREFIX)
GLIF_PROVIDER_ENDPOINT  = ET.QName('{%s}csProviderEndpoint' % GLIF_PREFIX)




class Topology:

    def __init__(self):
        self.networks = []


    def addNetwork(self, network):
        if network.name in [ n.name for n in self.networks ]:
            raise error.TopologyError('Network name must be unique (name: %s)' % network.name)

        self.networks.append(network)


    def getNetwork(self, network_name):
        for network in self.networks:
            if network.name == network_name:
                return network

        raise error.TopologyError('No network named %s' % network_name)


    def getEndpoint(self, network, endpoint):

        nw = self.getNetwork(network)
        for ep in nw.endpoints:
            if ep.endpoint == endpoint:
                return ep


    def findPaths(self, source_stp, dest_stp, bandwidth=None):
        """
        Find possible paths between two endpoints.
        """
        # check that STPs exist
        snw = self.getNetwork(source_stp.network)
        snw.getEndpoint(source_stp.endpoint)

        dnw = self.getNetwork(dest_stp.network)
        dnw.getEndpoint(dest_stp.endpoint)

        # find endpoint pairs
        #print "FIND PATH", source_stp, dest_stp

        routes = self.findPathEndpoints(source_stp, dest_stp)
        if bandwidths is not None:
            routes = self.filterBandwidth(routes, bandwidths)

        paths = []
        if routes == []:
            paths.append( nsa.Path(source_stp, dest_stp, []) )
        else:
            for sdps in routes:
                paths.append( nsa.Path(source_stp, dest_stp, sdps ) )

        return paths


    def findPathEndpoints(self, source_stp, dest_stp, visited_networks=None):

        #print "FIND PATH EPS", source_stp, visited_networks

        snw = self.getNetwork(source_stp.network)
        routes = []

        for ep in snw.endpoints:

            #print "  Path:", ep, " ", dest_stp

            if ep.dest_stp is None:
                #print "    Rejecting endpoint due to no pairing"
                continue

            if visited_networks is None:
                visited_networks = [ source_stp.network ]

            if ep.dest_stp.network in visited_networks:
                #print "    Rejecting endpoint due to loop"
                continue

            if ep.dest_stp.network == dest_stp.network:
                dest_ep = self.getEndpoint(ep.dest_stp.network, ep.dest_stp.endpoint)
                sp = nsa.SDP(ep, dest_ep)
                routes.append( [ sp ] )
            else:
                nvn = visited_networks[:] + [ ep.dest_stp.network ]
                subroutes = self.findPathEndpoints(ep.dest_stp, dest_stp, nvn)
                if subroutes:
                    for sr in subroutes:
                        src = sr[:]
                        dest_ep = self.getEndpoint(ep.dest_stp.network, ep.dest_stp.endpoint)
                        sp = nsa.SDP(ep, dest_ep)
                        src.insert(0, sp)
                        routes.append(  src  )

        return routes


    def filterBandwidth(self, paths_sdps, bandwidths):

        def hasBandwidth(route, bandwidths):
            for sdp in route:
                if sdp.stp1.available_capacity is not None and bandwidths.minimum is not None and sdp.stp1.available_capacity < bandwidths.minimum:
                    return False
                if sdp.stp2.available_capacity is not None and bandwidths.minimum is not None and sdp.stp2.available_capacity < bandwidths.minimum:
                    return False
            return True

        filtered_routes = [ route for route in paths_sdps if hasBandwidth(route, bandwidths) ]
        return filtered_routes


    def __str__(self):
        return '\n'.join( [ str(n) for n in self.networks ] )




def parseJSONTopology(topology_source):

    if isinstance(topology_source, file) or isinstance(topology_source, StringIO.StringIO):
        topology_data = json.load(topology_source)
    elif isinstance(topology_source, str):
        topology_data = json.loads(topology_source)
    else:
        raise error.TopologyError('Invalid topology source')

    topo = Topology()

    for network_name, network_info in topology_data.items():
        nn = nsa.NetworkServiceAgent(str(network_info['address']))
        nw = nsa.Network(network_name, nn)
        for epd in network_info.get('endpoints', []):
            dest_stp = None
            if 'dest-network' in epd and 'dest-ep' in epd:
                dest_stp = nsa.STP( epd['dest-network'], epd['dest-ep'] )
            ep = nsa.NetworkEndpoint(network_name, epd['name'], epd['config'], dest_stp, epd.get('max-capacity'), epd.get('available-capacity'))
            nw.addEndpoint(ep)

        topo.addNetwork(nw)

    return topo



def parseGOLETopology(topology_source):

    if isinstance(topology_source, file) or isinstance(topology_source, StringIO.StringIO):
        doc = ET.parse(topology_source)
    elif isinstance(topology_source, str):
        doc = ET.fromstring(topology_source)
    else:
        raise error.TopologyError('Invalid topology source')

    def stripGLIFPrefix(text):
        assert text.startswith(GLIF_PREFIX)
        return text.split(GLIF_PREFIX)[1]

    def stripURNPrefix(text):
        URN_PREFIX = 'urn:ogf:network:'
        assert text.startswith(URN_PREFIX)
        return text.split(':')[-1]

    stps = {}
    nsas = {}
    networks = {}

    for e in doc.getiterator():

        if e.tag == NAMED_INDIVIDUAL:

            # determine indivdual (resource) type
            se = e.getiterator(RDF_TYPE)[0]
            rt = stripGLIFPrefix(se.attrib[RDF_RESOURCE])
            rt_name = stripURNPrefix( e.attrib[RDF_ABOUT] )

            if rt == 'STP':
                connected_to = None
                for ct in e.getiterator(GLIF_CONNECTED_TO):
                    connected_to = stripURNPrefix( ct.attrib[RDF_RESOURCE] )
                stps[rt_name] = { 'connected_to' : connected_to }

            elif rt == 'NSNetwork':
                ns_stps = []
                for sse in e.getiterator(GLIF_HAS_STP):
                    ns_stps.append( stripURNPrefix( sse.attrib[RDF_RESOURCE] ) )
                ns_nsa = None
                for mb in e.getiterator(GLIF_MANAGED_BY):
                    ns_nsa = stripURNPrefix( mb.attrib[RDF_RESOURCE] )
                networks[rt_name] = { 'stps': ns_stps, 'nsa' : ns_nsa }

            elif rt == 'NSA':
                endpoint = None
                for cpe in e.getiterator(GLIF_PROVIDER_ENDPOINT):
                    endpoint = cpe.text or None
                nsas[rt_name] = { 'endpoint' : endpoint }

            else:
                print "Unknown Topology Resource", rt

    stp_rmap = {}

    for network_name, network_params in networks.items():
        for stp_name in network_params['stps']:
            stp_rmap[stp_name] = nsa.STP(network_name, stp_name)

    topo = Topology()

    for network_name, network_params in networks.items():

        nsa_name = network_params['nsa']
        nsa_info = nsas[nsa_name]
        nsa_endpoint = nsa_info.get('endpoint') or 'NSA_ENDPOINT_DUMMY'

        network_nsa = nsa.NetworkServiceAgent(nsa_name, nsa_endpoint)
        network = nsa.Network(network_name, network_nsa)

        for stp_name in network_params['stps']:
            dest_stp = stp_rmap.get(stps[stp_name]['connected_to'])
            ep = nsa.NetworkEndpoint(network_name, stp_name, None, dest_stp, None, None)
            network.addEndpoint(ep)

        topo.addNetwork(network)

    return topo

