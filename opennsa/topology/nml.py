"""
OpenNSA NML topology model.

Author: Henrik Thostrup Jensen <htj@nordu.net>

Copyright: NORDUnet (2011-2013)
"""

import itertools

from twisted.python import log

from opennsa import nsa, error


LOG_SYSTEM = 'opennsa.topology'

INGRESS = 'ingress'
EGRESS  = 'egress'

# Label types
ETHERNET = 'http://schemas.ogf.org/nml/2012/10/ethernet'
ETHERNET_VLAN = '{%s}vlan' % ETHERNET



class Port(object):

    def __init__(self, name, labels, remote_network=None, remote_port=None):

        assert ':' not in name, 'Invalid port name %s, must not contain ":"' % name
        if labels:
            assert type(labels) is list, 'labels must be list or None'
            for label in labels:
                assert type(label) is nsa.Label
        assert (remote_network and remote_port) or not (remote_network and remote_port), 'Must specify remote network and port or none of them'

        self.name           = name              # String  ; Base name, no network name or uri prefix
        self._labels        = labels            # [ nsa.Label ]  ; can be empty
        self.remote_network = remote_network    # String
        self.remote_port    = remote_port       # String


    def canMatchLabels(self, labels):
        if self._labels is None and labels is None:
            return True
        elif self._labels is None or labels is None:
            return False
        elif len(self._labels) != len(labels):
            return False
        elif len(self._labels) == 1: # len(labels) is identical
            if self._labels[0].type_ != labels[0].type_:
                return False
            try:
                self._labels[0].intersect(labels[0])
                return True
            except nsa.EmptyLabelSet:
                return False
        else:
            raise NotImplementedError('Multi-label matching not yet implemented')


    def isBidirectional(self):
        return False


    def labels(self):
        return self._labels


    def hasRemote(self):
        return self.remote_network != None



class InternalPort(Port):
    """
    Same as Port, but also has a bandwidth, so the pathfinder can probe for bandwidth.
    """
    def __init__(self, name, bandwidth, labels, remote_network=None, remote_port=None):

        super(InternalPort, self).__init__(name, labels, remote_network, remote_port)
        self.bandwidth = bandwidth


    def canProvideBandwidth(self, desired_bandwidth):
        return desired_bandwidth <= self.bandwidth



class BidirectionalPort(object):

    def __init__(self, name, inbound_port, outbound_port):
        assert type(name) is str, 'Name must be a string'
        assert isinstance(inbound_port, Port), 'Inbound port must be a <Port>'
        assert isinstance(outbound_port, Port), 'Outbound port must be a <Port>'
        assert [ l.type_ for l in inbound_port.labels() ] == [ l.type_ for l in outbound_port.labels() ], 'Port labels must match each other'

        self.name = name
        self.inbound_port  = inbound_port
        self.outbound_port = outbound_port


    def isBidirectional(self):
        return True


    def labels(self):
        # we only do one label at the moment
        if self.inbound_port.labels and self.outbound_port.labels:
            return [ self.inbound_port.labels()[0].intersect(self.outbound_port.labels()[0]) ]
        else:
            return []


    def canMatchLabels(self, labels):
        return self.inbound_port.canMatchLabels(labels) and self.outbound_port.canMatchLabels(labels)


    def hasRemote(self):
        return self.inbound_port.hasRemote() and self.outbound_port.hasRemote()


    def canProvideBandwidth(self, desired_bandwidth):
        return self.inbound_port.canProvideBandwidth(desired_bandwidth) and self.outbound_port.canProvideBandwidth(desired_bandwidth)

    def __repr__(self):
        return '<BidirectionalPort %s : %s/%s>' % (self.name, self.inbound_port.name, self.outbound_port.name)



class Network(object):

    def __init__(self, name, managing_nsa, inbound_ports, outbound_ports, bidirectional_ports):

        assert type(name) is str, 'Network name must be a string'
        assert type(inbound_ports) is list, 'Inbound ports must be a list'
        assert type(outbound_ports) is list, 'Outbound network ports must be a list'
        assert type(bidirectional_ports) is list, 'Bidirectional network ports must be a list'
        assert type(managing_nsa) is nsa.NetworkServiceAgent, 'Managing NSA must be a <NetworkServiceAgent>'

        # we should perhaps check that no ports has the same name

        self.name                = name          # String  ; just base name, no prefix or URI stuff
        self.inbound_ports       = inbound_ports or []
        self.outbound_ports      = outbound_ports or []
        self.bidirectional_ports = bidirectional_ports or []
        self.managing_nsa        = managing_nsa  # nsa.NetworkServiceAgent


    def getPort(self, port_name):
        for port in itertools.chain(self.inbound_ports, self.outbound_ports, self.bidirectional_ports):
            if port.name == port_name:
                return port
        raise error.TopologyError('No port named %s for network %s' %(port_name, self.name))


    def findPorts(self, bidirectionality, labels=None, exclude=None):
        matching_ports = []
        for port in itertools.chain(self.inbound_ports, self.outbound_ports, self.bidirectional_ports):
            if port.isBidirectional() == bidirectionality and (labels is None or port.canMatchLabels(labels)):
                if exclude and port.name == exclude:
                    continue
                matching_ports.append(port)
        return matching_ports


    def canSwapLabel(self, label_type):
        return label_type == ETHERNET_VLAN and self.name.startswith('urn:ogf:network:nordu.net:')



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


    def findDemarcationPort(self, network_name, port_name):
        # finds - if it exists - the demarcation port of a bidirectional port - have to go through unidirectional model
        port = self.getNetwork(network_name).getPort(port_name)
        assert isinstance(port, BidirectionalPort), 'Specified port for demarcation find is not bidirectional'
        if not port.hasRemote():
            return None
        if port.inbound_port.remote_network != port.outbound_port.remote_network:
            log.msg('Bidirectional port leads to multiple networks. Topology screwup?', system=LOG_SYSTEM)
            return None
        remote_network  = self.getNetwork(port.inbound_port.remote_network)
        inbound_remote  = port.inbound_port.remote_port
        outbound_remote = port.outbound_port.remote_port
        for rp in remote_network.findPorts(True):
            if isinstance(rp, BidirectionalPort) and rp.inbound_port.name == outbound_remote and rp.outbound_port.name == inbound_remote:
                return remote_network.name, rp.name
        return None


    def findPaths(self, source_stp, dest_stp, bandwidth, exclude_networks=None):

        source_port = self.getNetwork(source_stp.network).getPort(source_stp.port)
        dest_port   = self.getNetwork(dest_stp.network).getPort(dest_stp.port)

        if source_port.isBidirectional() or dest_port.isBidirectional():
            # at least one of the stps are bidirectional
            if not source_port.isBidirectional():
                raise error.TopologyError('Cannot connect bidirectional source with unidirectional destination')
            if not dest_port.isBidirectional():
                raise error.TopologyError('Cannot connect bidirectional destination with unidirectional source')
        else:
            # both ports are unidirectional
            if not (source_port.orientation, dest_port.orientation) in ( (nml.INGRESS, nml.EGRESS), (nml.EGRESS, nml.INGRESS) ):
                raise error.TopologyError('Cannot connect STPs of same unidirectional direction (%s -> %s)' % (source_port.orientation, dest_port.orientation))

        # these are only really interesting for the initial call, afterwards they just prune
        if not source_port.canMatchLabels(source_stp.labels):
            raise error.TopologyError('Source port cannot match labels for source STP')
        if not dest_port.canMatchLabels(dest_stp.labels):
            raise error.TopologyError('Desitination port cannot match labels for destination STP')
        if not source_port.canProvideBandwidth(bandwidth):
            raise error.BandwidthUnavailableError('Source port cannot provide enough bandwidth (%i)' % bandwidth)
        if not dest_port.canProvideBandwidth(bandwidth):
            raise error.BandwidthUnavailableError('Destination port cannot provide enough bandwidth (%i)' % bandwidth)

        return self._findPathsRecurse(source_stp, dest_stp, bandwidth)


    def _findPathsRecurse(self, source_stp, dest_stp, bandwidth, exclude_networks=None):

        source_network = self.getNetwork(source_stp.network)
        dest_network   = self.getNetwork(dest_stp.network)
        source_port    = source_network.getPort(source_stp.port)
        dest_port      = dest_network.getPort(dest_stp.port)

        if not (source_port.canMatchLabels(source_stp.labels) or dest_port.canMatchLabels(dest_stp.labels)):
            return []
        if not (source_port.canProvideBandwidth(bandwidth) and dest_port.canProvideBandwidth(bandwidth)):
            return []

        # this code heavily relies on the assumption that ports only have one label

        if source_port.isBidirectional() and dest_port.isBidirectional():
            # bidirectional path finding, easy case first
            if source_stp.network == dest_stp.network:
                # while it is possible to cross other network in order to connect to intra-network STPs
                # it is not something we really want to do in the real world, so we don't
                try:
                    if source_network.canSwapLabel(source_stp.labels[0].type_):
                        source_labels = source_port.labels()[0].intersect(source_stp.labels[0])
                        dest_labels   = dest_port.labels()[0].intersect(dest_stp.labels[0])
                    else:
                        source_labels = source_port.labels()[0].intersect(dest_port.labels()[0]).intersect(source_stp.labels[0]).intersect(dest_stp.labels[0])
                        dest_labels   = source_labels
                    link = nsa.Link(source_stp.network, source_stp.port, dest_stp.port, [source_labels], [dest_labels])
                    return [ [ link ] ]
                except nsa.EmptyLabelSet:
                    return [] # no path
            else:
                # ok, time for real pathfinding
                link_ports = source_network.findPorts(True, source_stp.labels, source_stp.port)
                link_ports = [ port for port in link_ports if port.hasRemote() ] # filter out termination ports
                links = []
                for lp in link_ports:
                    demarcation = self.findDemarcationPort(source_stp.network, lp.name)
                    if demarcation is None:
                        continue
                    if exclude_networks is not None and demarcation[0] in exclude_networks:
                        continue # don't do loops in path finding

                    demarcation_label = lp.labels()[0] if source_network.canSwapLabel(source_stp.labels[0].type_) else source_stp.labels[0].intersect(lp.labels()[0])
                    demarcation_stp = nsa.STP(demarcation[0], demarcation[1], [ demarcation_label ] )
                    sub_exclude_networks = [ source_network.name ] + (exclude_networks or [])
                    sub_links = self._findPathsRecurse(demarcation_stp, dest_stp, bandwidth, sub_exclude_networks)
                    # if we didn't find any sub paths, just continue
                    if not sub_links:
                        continue

                    for sl in sub_links:
                        # --
                        if source_network.canSwapLabel(source_stp.labels[0].type_):
                            source_label = source_port.labels()[0].intersect(source_stp.labels[0])
                            dest_label   = lp.labels()[0].intersect(sl[0].src_labels[0])
                        else:
                            source_label = source_port.labels()[0].intersect(source_stp.labels[0]).intersect(lp.labels()[0]).intersect(sl[0].src_labels[0])
                            dest_label   = source_label

                        first_link = nsa.Link(source_stp.network, source_stp.port, lp.name, [source_label], [dest_label])
                        path = [ first_link ] + sl
                        links.append(path)

                return sorted(links, key=len) # sort by length, shortest first

        else:
            raise error.TopologyError('Unidirectional path-finding not implemented yet')

