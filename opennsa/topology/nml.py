"""
OpenNSA NML topology model.

Author: Henrik Thostrup Jensen <htj@nordu.net>

Copyright: NORDUnet (2011-2013)
"""

import itertools
import datetime

from twisted.python import log

from opennsa import constants as cnt, nsa, error


LOG_SYSTEM = 'opennsa.topology'

INGRESS = 'ingress'
EGRESS  = 'egress'

URN_OGF_NETWORK = 'urn:ogf:network:'



class Port(object):

    def __init__(self, id_, name, labels, remote_port=None):

        assert not id_.startswith('urn:'), 'URNs are not used in core OpenNSA NML (id: %s)' % id_
        assert ':' not in name, 'Invalid port name %s, must not contain ":"' % name
        if labels:
            assert type(labels) is list, 'labels must be list or None'
            for label in labels:
                assert type(label) is nsa.Label

        self.id_            = id_               # The URN of the port
        self.name           = name              # String  ; Base name, no network name or uri prefix
        self._labels        = labels            # [ nsa.Label ]  ; can be empty
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
        return self.remote_port != None


    def __repr__(self):
        return '<Port %s (%s) # %s -> %s>' % (self.id_, self.name, self._labels, self.remote_port)



class InternalPort(Port):
    """
    Same as Port, but also has a bandwidth, so the pathfinder can probe for bandwidth.
    """
    def __init__(self, id_, name, bandwidth, labels, remote_port=None):
        super(InternalPort, self).__init__(id_, name, labels, remote_port)
        self.bandwidth = bandwidth


    def canProvideBandwidth(self, desired_bandwidth):
        return desired_bandwidth <= self.bandwidth


    def __repr__(self):
        return '<InternalPort %s (%s) # %s : %i -> %s>' % (self.id_, self.name, self._labels, self.bandwidth, self.remote_port)



class BidirectionalPort(object):

    def __init__(self, id_, name, inbound_port, outbound_port):
        assert type(id_) is str, 'Port id must be a string'
        assert type(name) is str, 'Port name must be a string'
        assert isinstance(inbound_port, Port), 'Inbound port must be a <Port>'
        assert isinstance(outbound_port, Port), 'Outbound port must be a <Port>'
        assert [ l.type_ for l in inbound_port.labels() ] == [ l.type_ for l in outbound_port.labels() ], 'Port labels must match each other'
        assert not id_.startswith('urn:'), 'URNs are not used in core OpenNSA NML (id: %s)' % id_

        self.id_ = id_
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
        return '<BidirectionalPort %s (%s) : %s/%s>' % (self.id_, self.name, self.inbound_port.name, self.outbound_port.name)



class Network(object):

    def __init__(self, id_, name, inbound_ports, outbound_ports, bidirectional_ports, version=None):

        assert type(id_) is str, 'Network id must be a string'
        assert type(name) is str, 'Network name must be a string'
        assert type(inbound_ports) is list, 'Inbound ports must be a list'
        assert type(outbound_ports) is list, 'Outbound network ports must be a list'
        assert type(bidirectional_ports) is list, 'Bidirectional network ports must be a list'
        assert not id_.startswith('urn:'), 'URNs are not used in core OpenNSA NML (id: %s)' % id_

        # we should perhaps check that no ports has the same name

        self.id_                 = id_           # String  ; the urn of the network topology
        self.name                = name          # String  ; just base name, no prefix or URI stuff
        self.inbound_ports       = inbound_ports or []
        self.outbound_ports      = outbound_ports or []
        self.bidirectional_ports = bidirectional_ports or []
        self.version             = version or datetime.datetime.utcnow()


    def getPort(self, port_id):
        for port in itertools.chain(self.inbound_ports, self.outbound_ports, self.bidirectional_ports):
            if port.id_ == port_id:
                return port
        # better error message
        ports = [ p.id_ for p in list(itertools.chain(self.inbound_ports, self.outbound_ports, self.bidirectional_ports)) ]
        raise error.TopologyError('No port named %s for network %s (ports: %s)' %(port_id, self.name, str(ports)))


    def findPorts(self, bidirectionality, labels=None, exclude=None):
        matching_ports = []
        for port in itertools.chain(self.inbound_ports, self.outbound_ports, self.bidirectional_ports):
            if port.isBidirectional() == bidirectionality and (labels is None or port.canMatchLabels(labels)):
                if exclude and port.id_ == exclude:
                    continue
                matching_ports.append(port)
        return matching_ports


    def canSwapLabel(self, label_type):
        return label_type == cnt.ETHERNET_VLAN and self.name.startswith('urn:ogf:network:nordu.net:')



class Topology(object):

    def __init__(self):
        self.networks = {} # network_name -> ( Network, nsa.NetworkServiceAgent)


    def addNetwork(self, network, managing_nsa):
        assert type(network) is Network
        assert type(managing_nsa) is nsa.NetworkServiceAgent

        if network.id_ in self.networks:
            raise error.TopologyError('Entry for network with id %s already exists' % network.id_)

        self.networks[network.id_] = (network, managing_nsa)


    def updateNetwork(self, network, managing_nsa):
        # update an existing network entry
        existing_entry = self.networks.pop(network.id_, None) # note - we may get none here (for new network)
        try:
            self.addNetwork(network, managing_nsa)
        except error.TopologyError as e:
            log.msg('Error updating network entry for %s. Reason: %s' % (network.id_, str(e)))
            if existing_entry:
                self.networks[network.id_] = existing_entry # restore old entry
            raise e


    def getNetwork(self, network_id):
        try:
            return self.networks[network_id][0]
        except KeyError:
            raise error.TopologyError('No network with id %s' % (network_id))


    def getNetworkPort(self, port_id):
        for network_id, (network,_) in self.networks.items():
            try:
                port = network.getPort(port_id)
                return network_id, port
            except error.TopologyError:
                continue
        else:
            raise error.TopologyError('Cannot find port with id %s in topology' % port_id)


    def getNSA(self, network_id):
        try:
            return self.networks[network_id][1]
        except KeyError as e:
            raise error.TopologyError('No NSA for network with id %s (%s)' % (network_id, str(e)))


    def findDemarcationPort(self, port):
        # finds - if it exists - the demarcation port of a bidirectional port - have to go through unidirectional model
        assert isinstance(port, BidirectionalPort), 'Specified port for demarcation find is not bidirectional'
        if not port.hasRemote():
            return None

        try:
            remote_network_in,  remote_port_in  = self.getNetworkPort(port.outbound_port.remote_port)
            remote_network_out, remote_port_out = self.getNetworkPort(port.inbound_port.remote_port)

            if remote_network_in != remote_network_out:
                log.msg('Bidirectional port %s leads to multiple networks. Topology screwup?' % port_id, system=LOG_SYSTEM)
                return None

        except error.TopologyError as e:
            log.msg('Error looking up demarcation port for %s%%%s. Message: %s' % (network_id, port_id, str(e)), system=LOG_SYSTEM)
            return None

        remote_network = self.getNetwork(remote_network_in)

        for rp in remote_network.findPorts(True):
            if isinstance(rp, BidirectionalPort) and rp.inbound_port.id_ == remote_port_in.id_ and rp.outbound_port.id_ == remote_port_out.id_:
                return remote_network.id_, rp.id_
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
            if not (source_port.orientation, dest_port.orientation) in ( (INGRESS, EGRESS), (EGRESS, INGRESS) ):
                raise error.TopologyError('Cannot connect STPs of same unidirectional direction (%s -> %s)' % (source_port.orientation, dest_port.orientation))

        # these are only really interesting for the initial call, afterwards they just prune
        if not source_port.canMatchLabels(source_stp.labels):
            raise error.TopologyError('Source port %s (labels %s) cannot match labels for source STP (%s)' % (source_port.id_, source_port.labels(), source_stp.labels))
        if not dest_port.canMatchLabels(dest_stp.labels):
            raise error.TopologyError('Desitination port %s (labels %s) cannot match labels for destination STP %s' % (dest_port.id_, dest_port.labels(), dest_stp.labels))
#        if not source_port.canProvideBandwidth(bandwidth):
#            raise error.BandwidthUnavailableError('Source port cannot provide enough bandwidth (%i)' % bandwidth)
#        if not dest_port.canProvideBandwidth(bandwidth):
#            raise error.BandwidthUnavailableError('Destination port cannot provide enough bandwidth (%i)' % bandwidth)

        return self._findPathsRecurse(source_stp, dest_stp, bandwidth)


    def _findPathsRecurse(self, source_stp, dest_stp, bandwidth, exclude_networks=None):

        source_network = self.getNetwork(source_stp.network)
        dest_network   = self.getNetwork(dest_stp.network)
        source_port    = source_network.getPort(source_stp.port)
        dest_port      = dest_network.getPort(dest_stp.port)

        if not (source_port.canMatchLabels(source_stp.labels) or dest_port.canMatchLabels(dest_stp.labels)):
            return []
#        if not (source_port.canProvideBandwidth(bandwidth) and dest_port.canProvideBandwidth(bandwidth)):
#            return []

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
                    demarcation = self.findDemarcationPort(lp)
                    if demarcation is None:
                        continue

                    d_network_id, d_port_id = demarcation

                    if exclude_networks is not None and demarcation[0] in exclude_networks:
                        continue # don't do loops in path finding

                    demarcation_label = lp.labels()[0] if source_network.canSwapLabel(source_stp.labels[0].type_) else source_stp.labels[0].intersect(lp.labels()[0])
                    demarcation_stp = nsa.STP(demarcation[0], demarcation[1], [ demarcation_label ] )
                    sub_exclude_networks = [ source_network.id_ ] + (exclude_networks or [])
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

                        first_link = nsa.Link(source_stp.network, source_stp.port, lp.id_, [source_label], [dest_label])
                        path = [ first_link ] + sl
                        links.append(path)

                return sorted(links, key=len) # sort by length, shortest first

        else:
            raise error.TopologyError('Unidirectional path-finding not implemented yet')

