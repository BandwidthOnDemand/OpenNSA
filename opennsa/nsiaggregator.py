"""
OpenNSA NSI Service -> Backend adaptor (router).

Author: Henrik Thostrup Jensen <htj@nordu.net>
Copyright: NORDUnet (2011)
"""

import random

from zope.interface import implements

from twisted.python import log
from twisted.internet import defer

from opennsa.interface import NSIServiceInterface
from opennsa import nsa, error, topology, jsonrpc



class NSIAggregator:

    implements(NSIServiceInterface)

    def __init__(self, network, backend, topology_file):
        self.network = network
        self.backend = backend

        self.topology = topology.Topology()
        self.topology.parseTopology(open(topology_file))

        self.connections = {}


    def reserve(self, requester_nsa, provider_nsa, connection_id, global_reservation_id, description, service_parameters, session_security_attributes):

#        log.msg("Reserve request: %s, %s, %s" % (connection_id, global_reservation_id, description))

        nsa_identity = requester_nsa.address

        if connection_id in self.connections.get(nsa_identity, {}):
            raise error.ReserveError('Reservation with connection id %s already exists' % connection_id)

        source_stp = service_parameters.source_stp
        dest_stp   = service_parameters.dest_stp

        def reservationMade(internal_reservation_id, sub_connections=None):
            #nsa_identity = requester_nsa.address
            self.connections.setdefault(nsa_identity, {})
            connection = nsa.Connection(connection_id, internal_reservation_id, source_stp, dest_stp, global_reservation_id, sub_connections)
            self.connections[nsa_identity][connection_id] = connection
            log.msg('Reservation for connection %s (%s) created. Global id %s' % (connection_id, internal_reservation_id, global_reservation_id), system='opennsa.NSIAggregator')
            return connection

        # figure out nature of request

        link_info = (source_stp.network, source_stp.endpoint, dest_stp.network, dest_stp.endpoint, self.network)

        if source_stp.network == self.network and dest_stp.network == self.network:
            log.msg('Simple link creation: %s:%s -> %s:%s (%s)' % link_info, system='opennsa.NSIAggregator')
            # make an internal link, no sub requests
            d = self.backend.reserve(source_stp.endpoint, dest_stp.endpoint, service_parameters)
            d.addCallback(reservationMade)
            d.addCallback(lambda _ : connection_id)
            return d

        elif source_stp.network == self.network:
            # make link and chain on - common chaining
            log.msg('Common chain creation: %s:%s -> %s:%s (%s)' % link_info, system='opennsa.NSIAggregator')

            links = self.topology.findLinks(source_stp, dest_stp)
            # check for no links
            links.sort(key=lambda e : len(e.endpoint_pairs))
            selected_link = links[0] # shortest link
            log.msg('Attempting to create link %s' % selected_link, system='opennsa.NSIAggregator')

            assert selected_link.source_stp.network == self.network

            chain_network = selected_link.endpoint_pairs[0].stp2.network

            def issueChainReservation(connection):
                own_address = self.topology.getNetwork(self.network).nsa.address # is this ok? why not?
                own_nsa = nsa.NetworkServiceAgent(own_address, None)

                chain_network_nsa = self.topology.getNetwork(chain_network).nsa

                sub_conn_id = 'int-ccid' + ''.join( [ str(int(random.random() * 10)) for _ in range(4) ] )

                new_source_stp      = selected_link.endpoint_pairs[0].stp2
                new_service_params  = nsa.ServiceParameters('', '', new_source_stp, dest_stp)

                def chainedReservationMade(sub_conn_id):
                    connection.sub_connections.append( ( chain_network, sub_conn_id) )
                    return connection

                proxy = jsonrpc.JSONRPCNSIClient()
                d = proxy.reserve(own_nsa, chain_network_nsa, sub_conn_id, global_reservation_id, description, new_service_params, None)
                d.addCallback(chainedReservationMade)
                d.addCallback(lambda _ : connection_id)
                return d

            d = self.backend.reserve(selected_link.source_stp.endpoint, selected_link.endpoint_pairs[0].stp1.endpoint, service_parameters)
            d.addCallback(reservationMade)
            d.addCallback(issueChainReservation)
            return d



        elif dest_stp.network == self.network:
            # make link and chain on - backwards chaining
            log.msg('Backwards chain creation: %s:%s -> %s:%s (%s)' % link_info, system='opennsa.NSIAggregator')
            raise NotImplementedError('Backwards chain reservation')


        else:
            log.msg('Tree creation:  %s:%s -> %s:%s (%s)' % link_info, system='opennsa.NSIAggregator')
            raise NotImplementedError('Tree reservation')



    def cancelReservation(self, requester_nsa, provider_nsa, connection_id, session_security_attributes):

        conn = self.connections.get(requester_nsa.address, {}).get(connection_id, None)
        if conn is None:
            raise error.CancelReservationError('No connection with id %s for NSA with address %s' % (connection_id, requester_nsa.address))
        # check state before cancelling

        def reservationCancelled(_):
            pass
            # update state

        d = self.backend.cancelReservation(conn.internal_reservation_id)
        return d


    def provision(self, requester_nsa, provider_nsa, connection_id, session_security_attributes):

        conn = self.connections.get(requester_nsa.address, {}).get(connection_id, None)
        if conn is None:
            raise error.ProvisionError('No connection with id %s for NSA with address %s' % (connection_id, requester_nsa.address))
        # check state is ok before provisioning

        def internalProvisionMade(internal_connection_id):
            log.msg('Connection %s/%s internally provisioned' % (connection_id, internal_connection_id), system='opennsa.NSIAggregator')
            conn.internal_connection_id = internal_connection_id
            # update state!
            return connection_id

        def provisionComplete(results):
            log.msg('Connection %s and all sub connections provisioned' % connection_id, system='opennsa.NSIAggregator')
            print "R", results
            return connection_id

        # if there are any sub connections, call must be issues to those
        di = self.backend.provision(conn.internal_reservation_id)
        di.addCallback(internalProvisionMade)

        defs = [ di ]

        for sub_network, sub_conn_id in conn.sub_connections:
            sub_network_nsa = self.topology.getNetwork(sub_network).nsa

            # this should be made class wide sometime
            own_address = self.topology.getNetwork(self.network).nsa.address # is this ok? why not?
            own_nsa = nsa.NetworkServiceAgent(own_address, None)

            def subProvisionMade(conn_id, sub_conn_id, sub_network):
                log.msg('Sub connection %s in network %s provisioned' % (sub_conn_id, sub_network), system='opennsa.NSIAggregator')
                return conn_id

            proxy = jsonrpc.JSONRPCNSIClient()
            d = proxy.provision(own_nsa, sub_network_nsa, sub_conn_id, None)
            d.addCallback(subProvisionMade, sub_conn_id, sub_network)
            defs.append(d)

        d = defer.DeferredList(defs)
        d.addCallback(provisionComplete) # error handling, nahh :-)


        return d


    def releaseProvision(self, requester_nsa, provider_nsa, connection_id, session_security_attributes):

        conn = self.connections.get(requester_nsa.address, {}).get(connection_id, None)
        if conn is None:
            raise error.ReleaseProvisionError('No connection with id %s for NSA with address %s' % (connection_id, requester_nsa.address))

        def provisionReleased(internal_reservation_id):
            conn.internal_reservation_id = internal_reservation_id
            conn.internal_connection_id = None

        d = self.backend.releaseProvision(conn.internal_connection_id)
        d.addCallback(provisionReleased)
        return d


    def query(self, requester_nsa, provider_nsa, query_filter, session_security_attributes):

        log.msg('-', system='opennsa.NSIAggregator')


