"""
Connection abstraction.

Author: Henrik Thostrup Jensen <htj@nordu.net>
Copyright: NORDUnet (2011-2012)
"""
import string
import random
import datetime

from twisted.python import log, failure
from twisted.internet import defer

from opennsa import error, nsa, state, database



LOG_SYSTEM = 'Aggregator'



#def connPath(conn):
#    """
#    Utility function for getting a string with the source and dest STP of connection.
#    """
#    source_stp, dest_stp = conn.stps()
#    return '<%s:%s--%s:%s>' % (source_stp.network, source_stp.endpoint, dest_stp.network, dest_stp.endpoint)


def shortLabel(labels):
    # create a log friendly string representation of a lbel
    lbs = []
    for label in labels:
        if '}' in label.type_:
            name = label.type_.split('}',1)[1][1:]
        else:
            name = label.type_
        lbs.append( name + ':' + label.labelValue() )
    return ','.join(lbs)


def _buildErrorMessage(results, action):

    # should probably seperate loggin somehow
    failures = [ (conn, f) for (success, f), conn in zip(results, self.connections()) if success is False ]
    failure_msgs = [ conn.curator() + ' ' + connPath(conn) + ' ' + f.getErrorMessage() for (conn, f) in failures ]
    log.msg('Connection %s: %i/%i %s failed.' % (self.connection_id, len(failures), len(results), action), system=LOG_SYSTEM)
    for msg in failure_msgs:
        log.msg('* Failure: ' + msg, system=LOG_SYSTEM)

    # build the error message to send back
    if len(results) == 1:
        # only one connection, we just return the plain failure
        error_msg = failures[0][1].getErrorMessage()
    else:
        # multiple failures, here we build a more complicated error string
        error_msg = '%i/%i %s failed: %s' % (len(failures), len(results), action, '. '.join(failure_msgs))

    return error_msg


def _createAggregateException(results, action, default_error=error.InternalServerError):

    # need to handle multi-errors better, but infrastructure isn't there yet
    failures = [ conn for success,conn in results if not success ]
    if len(failures) == 0:
        # not supposed to happen
        return error.InternalServerError('_createAggregateException called with no failures')
    if len(results) == 1 and len(failures) == 1:
        return failures[0]
    else:
        error_msg = _buildErrorMessage(results, action)
        return default_error(error_msg)


def _createAggregateFailure(results, action):

    err = _createAggregateException(results, action)
    return failure.Failure(err)



class Aggregator:

    def __init__(self, network, nsa_, topology, parent_requester, providers):
        self.network = network
        self.nsa_ = nsa_
        self.topology = topology

        self.parent_requester   = parent_requester
        self.providers          = providers


    def getConnection(self, requester_nsa, connection_id):

        # need to do authz here

        def gotResult(connections):
            # we should get 0 or 1 here since connection id is unique
            if len(connections) == 0:
                return defer.fail( error.ConnectionNonExistentError('No connection with id %s' % connection_id) )
            return connections[0]

        d = database.ServiceConnection.findBy(connection_id=connection_id)
        d.addCallback(gotResult)
        return d


    def getSubConnection(self, provider_nsa, connection_id):

        def gotResult(connections):
            # we should get 0 or 1 here since provider_nsa + connection id is unique
            if len(connections) == 0:
                return defer.fail( error.ConnectionNonExistentError('No sub connection with connection id %s at provider %s' % (connection_id, provider_nsa) ) )
            return connections[0]

        d = database.SubConnection.findBy(provider_nsa=provider_nsa, connection_id=connection_id)
        d.addCallback(gotResult)
        return d


    @defer.inlineCallbacks
    def reserve(self, header, connection_id, global_reservation_id, description, service_params):

        log.msg('', system=LOG_SYSTEM)
        log.msg('Reserve request. NSA: %s. Connection ID: %s' % (header.requester_nsa, connection_id), system=LOG_SYSTEM)

        # rethink with modify
        if connection_id != None:
            connection_exists = yield database.ServiceConnection.exists(['connection_id = ?', connection_id])
            if connection_exists:
                raise error.ConnectionExistsError('Connection with id %s already exists' % connection_id)
            raise NotImplementedError('Cannot handly modification of existing connections yet')

        connection_id = 'NU-T' + ''.join( [ random.choice(string.hexdigits[:16]) for _ in range(12) ] )

        source_stp = service_params.source_stp
        dest_stp   = service_params.dest_stp

        # check that we know the networks
        self.topology.getNetwork(source_stp.network)
        self.topology.getNetwork(dest_stp.network)

        # if the link terminates at our network, check that ports exists
        if source_stp.network == self.network:
            self.topology.getNetwork(self.network).getPort(source_stp.port)
        if dest_stp.network == self.network:
            self.topology.getNetwork(self.network).getPort(dest_stp.port)

        if source_stp == dest_stp and source_stp.label.singleValue():
            raise error.TopologyError('Cannot connect STP %s to itself.' % source_stp)

        conn = database.ServiceConnection(connection_id=connection_id, revision=0, global_reservation_id=global_reservation_id, description=description,
                            requester_nsa=header.requester_nsa, requester_url=header.reply_to, reserve_time=datetime.datetime.utcnow(),
                            reservation_state=state.RESERVE_START, provision_state=state.RELEASED, lifecycle_state=state.INITIAL,
                            source_network=source_stp.network, source_port=source_stp.port, source_labels=source_stp.labels,
                            dest_network=dest_stp.network, dest_port=dest_stp.port, dest_labels=dest_stp.labels,
                            start_time=service_params.start_time, end_time=service_params.end_time, bandwidth=service_params.bandwidth)
        yield conn.save()

        # Here we should return / callback and spawn off the path creation

        # Note: At his point STP Labels are candidates and they will need to be changed later

    #    def reserveRequestsDone(results):
    #        successes = [ r[0] for r in results ]
    #        if all(successes):
    #            state.reserved(conn)
    #            log.msg('Connection %s: Reserve succeeded' % self.connection_id, system=LOG_SYSTEM)
    #            self.scheduler.scheduleTransition(self.service_parameters.start_time, scheduled, state.RELEASED)
    #            return self
    #
    #        else:
    #            # terminate non-failed connections
    #            # currently we don't try and be too clever about cleaning, just do it, and switch state
    #            defs = []
    #            reserved_connections = [ conn for success,conn in results if success ]
    #            for rc in reserved_connections:
    #                d = rc.terminate()
    #                d.addCallbacks(
    #                    lambda c : log.msg('Succesfully terminated sub connection after partial reservation failure %s %s' % (c.curator(), connPath(c)) , system=LOG_SYSTEM),
    #                    lambda f : log.msg('Error terminating connection after partial-reservation failure: %s' % str(f), system=LOG_SYSTEM)
    #                )
    #                defs.append(d)
    #            dl = defer.DeferredList(defs)
    #            dl.addCallback( self.state.terminatedFailed )
    #
    #            err = self._createAggregateFailure(results, 'reservations', error.ConnectionCreateError)
    #            return err

        yield state.reserveChecking(conn) # this also acts a lock

        if conn.source_network == self.network and conn.dest_network == self.network:
            path_info = ( conn.connection_id, self.network, conn.source_port, shortLabel(conn.source_labels), conn.dest_port, shortLabel(conn.dest_labels) )
            log.msg('Connection %s: Local link creation: %s %s#%s -> %s#%s' % path_info, system=LOG_SYSTEM)
            paths = [ [ nsa.Link(self.network, conn.source_port, conn.dest_port, conn.source_labels, conn.dest_labels) ] ]

        else:
            # log about creation and the connection type
            path_info = ( conn.connection_id, conn.source_network, conn.source_port, conn.dest_network, conn.dest_port, conn.nsa)
            log.msg('Connection %s: Aggregate path creation: %s:%s -> %s:%s (%s)' % path_info, system=LOG_SYSTEM)
            # making the connection is the same for all though :-)
            paths = self.topology.findPaths(source_stp, dest_stp)

            # error out if we could not find a path
            if not paths:
                error_msg = 'Could not find a path for route %s:%s -> %s:%s' % (source_stp.network, source_stp.port, dest_stp.network, dest_stp.port)
                log.msg(error_msg, system=LOG_SYSTEM)
                raise error.TopologyError(error_msg)

            paths.sort(key=lambda e : len(e.links()))

        selected_path = paths[0] # shortest path
        log_path = ' -> '.join( [ str(p) for p in selected_path ] )
        log.msg('Attempting to create path %s' % log_path, system=LOG_SYSTEM)

        for link in selected_path:
            provider_nsa = self.topology.getNetwork(link.network).managing_nsa
            if not provider_nsa.urn() in self.providers:
                raise error.ConnectionCreateError('Cannot create link at network %s, no available provider for NSA %s' % (link.network, provider_nsa.urn()))

        defs = []
        for idx, link in enumerate(selected_path):

            provider_nsa = self.topology.getNetwork(link.network).managing_nsa
            provider     = self.providers[provider_nsa.urn()]

            ssp  = nsa.ServiceParameters(conn.start_time, conn.end_time,
                                         nsa.STP(link.network, link.src_port, labels=link.src_labels),
                                         nsa.STP(link.network, link.dst_port, labels=link.dst_labels),
                                         conn.bandwidth)


            header = nsa.NSIHeader(self.nsa_.urn(), provider_nsa.urn(), []) # need to something more here - or delegate to protocl stack (yes)
            d = provider.reserve(header, None, conn.global_reservation_id, conn.description, ssp)

            @defer.inlineCallbacks
            def reserveResponse(connection_id, link_provider_nsa, order_id):
                # need to collapse the end stps in Connection object
                log.msg('Connection reservation for %s via %s acked' % (connection_id, link_provider_nsa), debug=True, system=LOG_SYSTEM)
                # should probably do some sanity checks here
                sp = service_params
                local_link = True if link_provider_nsa == self.nsa_ else False
                sc = database.SubConnection(provider_nsa=link_provider_nsa.urn(),
                                            connection_id=connection_id, local_link=local_link, revision=0, service_connection_id=conn.id, order_id=order_id,
                                            global_reservation_id=global_reservation_id, description=description,
                                            reservation_state=state.RESERVE_START, provision_state=state.RELEASED, lifecycle_state=state.INITIAL, data_plane_active=False,
                                            source_network=sp.source_stp.network, source_port=sp.source_stp.port, source_labels=sp.source_stp.labels,
                                            dest_network=sp.dest_stp.network, dest_port=sp.dest_stp.port, dest_labels=sp.dest_stp.labels,
                                            start_time=sp.start_time.isoformat(), end_time=sp.end_time.isoformat(), bandwidth=sp.bandwidth)
                yield sc.save()
                defer.returnValue(sc)

            d.addCallback(reserveResponse, provider_nsa, idx)
            defs.append(d)

        results = yield defer.DeferredList(defs, consumeErrors=True) # doesn't errback
        successes = [ r[0] for r in results ]

        if all(successes):
            log.msg('Connection %s: Reserve acked' % conn.connection_id, system=LOG_SYSTEM)
            defer.returnValue(connection_id)

        else:
            # terminate non-failed connections
            # currently we don't try and be too clever about cleaning, just do it, and switch state
            yield state.terminating(conn)
            defs = []
            reserved_connections = [ sc for success,sc in results if success ]
            for rc in reserved_connections:
                d = rc.terminate()
                d.addCallbacks(
                    lambda c : log.msg('Succesfully terminated sub connection after partial reservation failure %s %s' % (c.curator(), connPath(c)) , system=LOG_SYSTEM),
                    lambda f : log.msg('Error terminating connection after partial-reservation failure: %s' % str(f), system=LOG_SYSTEM)
                )
                defs.append(d)
            dl = defer.DeferredList(defs)
            yield dl
            yield state.terminated(conn)

            err = _createAggregateException(results, 'reservations', error.ConnectionCreateError)
            raise err


    @defer.inlineCallbacks
    def reserveCommit(self, header, connection_id):

        log.msg('', system=LOG_SYSTEM)
        log.msg('ReserveCommit request. NSA: %s. Connection ID: %s' % (header.requester_nsa, connection_id), system=LOG_SYSTEM)

        conn = yield self.getConnection(header.requester_nsa, connection_id)

        if conn.lifecycle_state == state.TERMINATED:
            raise error.ConnectionGoneError('Connection %s has been terminated')

        yield state.reserveCommit(conn)

        defs = []
        sub_connections = yield conn.SubConnections.get()
        for sc in sub_connections:
            # we assume a provider is available
            provider = self.providers[sc.provider_nsa]
            req_header = nsa.NSIHeader(self.nsa_.urn(), sc.provider_nsa, [])
            # we should probably mark as committing before sending message...
            d = provider.reserveCommit(req_header, sc.connection_id)
            defs.append(d)

        results = yield defer.DeferredList(defs, consumeErrors=True)

        successes = [ r[0] for r in results ]
        if all(successes):
            log.msg('Connection %s: ReserveCommit messages acked' % conn.connection_id, system=LOG_SYSTEM)
            defer.returnValue(connection_id)

        else:
            n_success = sum( [ 1 for s in successes if s ] )
            log.msg('Connection %s. Only %i of %i commit acked successfully' % (connection_id, n_success, len(defs)), system=LOG_SYSTEM)
            raise _createAggregateException(results, 'committed', error.ConnectionError)


    @defer.inlineCallbacks
    def reserveAbort(self, header, connection_id):

        log.msg('', system=LOG_SYSTEM)
        log.msg('ReserveAbort request. NSA: %s. Connection ID: %s' % (header.requester_nsa, connection_id), system=LOG_SYSTEM)

        conn = yield self.getConnection(header.requester_nsa, connection_id)

        if conn.lifecycle_state == state.TERMINATED:
            raise error.ConnectionGoneError('Connection %s has been terminated')

        yield state.reserveAbort(conn)

        save_defs = []
        defs = []
        sub_connections = yield conn.SubConnections.get()
        for sc in sub_connections:
            save_defs.append( state.reserveAbort(sc) )
            provider = self.providers[sc.provider_nsa]
            header = nsa.NSIHeader(self.nsa_.urn(), sc.provider_nsa, [])
            d = provider.reserveAbort(header, sc.connection_id)
            defs.append(d)

        yield defer.DeferredList(save_defs, consumeErrors=True)

        results = yield defer.DeferredList(defs, consumeErrors=True)

        successes = [ r[0] for r in results ]
        if all(successes):
            log.msg('Connection %s: All ReserveAbort acked' % conn.connection_id, system=LOG_SYSTEM)
            defer.returnValue(connection_id)

        else:
            n_success = sum( [ 1 for s in successes if s ] )
            log.msg('Connection %s. Only %i of %i connections aborted' % (self.connection_id, len(n_success), len(defs)), system=LOG_SYSTEM)
            raise self._createAggregateException(results, 'aborted', error.ConnectionError)


    @defer.inlineCallbacks
    def provision(self, header, connection_id):

        log.msg('', system=LOG_SYSTEM)
        log.msg('Provision request. NSA: %s. Connection ID: %s' % (header.requester_nsa, connection_id), system=LOG_SYSTEM)

        conn = yield self.getConnection(header.requester_nsa, connection_id)

        if conn.lifecycle_state == state.TERMINATED:
            raise error.ConnectionGoneError('Connection %s has been terminated')

        yield state.provisioning(conn)

        save_defs = []
        defs = []
        sub_connections = yield conn.SubConnections.get()
        for sc in sub_connections:
            save_defs.append( state.provisioning(sc) )
            provider = self.providers[sc.provider_nsa]
            header = nsa.NSIHeader(self.nsa_.urn(), sc.provider_nsa, [])
            d = provider.provision(header, sc.connection_id)
            defs.append(d)

        yield defer.DeferredList(save_defs, consumeErrors=True)

        results = yield defer.DeferredList(defs, consumeErrors=True)
        successes = [ r[0] for r in results ]
        if all(successes):
            # this just means we got an ack from all children
            defer.returnValue(connection_id)
        else:
            n_success = sum( [ 1 for s in successes if s ] )
            log.msg('Connection %s. Provision failure. %i of %i connections successfully acked' % (connection_id, n_success, len(defs)), system=LOG_SYSTEM)
            raise _createAggregateException(results, 'provision', error.ConnectionError)


    @defer.inlineCallbacks
    def release(self, header, connection_id):

        log.msg('', system=LOG_SYSTEM)
        log.msg('Release request. NSA: %s. Connection ID: %s' % (header.requester_nsa, connection_id), system=LOG_SYSTEM)

        conn = yield self.getConnection(header.requester_nsa, connection_id)

        if conn.lifecycle_state == state.TERMINATED:
            raise error.ConnectionGoneError('Connection %s has been terminated')

        yield state.releasing(conn)

        save_defs = []
        defs = []
        sub_connections = yield conn.SubConnections.get()
        for sc in sub_connections:
            save_defs.append( state.releasing(sc) )
            provider = self.providers[sc.provider_nsa]
            header = nsa.NSIHeader(self.nsa_.urn(), sc.provider_nsa, [])
            d = provider.release(header, sc.connection_id)
            defs.append(d)

        yield defer.DeferredList(save_defs, consumeErrors=True)

        results = yield defer.DeferredList(defs, consumeErrors=True)
        successes = [ r[0] for r in results ]
        if all(successes):
            # got ack from all children
            defer.returnValue(connection_id)

        else:
            n_success = sum( [ 1 for s in successes if s ] )
            log.msg('Connection %s. Only %i of %i connections successfully released' % (self.connection_id, n_success, len(defs)), system=LOG_SYSTEM)
            raise self._createAggregateException(results, 'release', error.ConnectionError)


    @defer.inlineCallbacks
    def terminate(self, header, connection_id):

        log.msg('', system=LOG_SYSTEM)
        log.msg('Terminate request. NSA: %s. Connection ID: %s' % (header.requester_nsa, connection_id), system=LOG_SYSTEM)

        conn = yield self.getConnection(header.requester_nsa, connection_id)

        if conn.lifecycle_state == state.TERMINATED:
            defer.returnValue(connection_id) # all good

        yield state.terminating(conn)

        defs = []
        sub_connections = yield conn.SubConnections.get()
        for sc in sub_connections:
            # we assume a provider is available
            provider = self.providers[sc.provider_nsa]
            header = nsa.NSIHeader(self.nsa_.urn(), sc.provider_nsa, [])
            d = provider.terminate(header, sc.connection_id)
            defs.append(d)

        results = yield defer.DeferredList(defs, consumeErrors=True)

        successes = [ r[0] for r in results ]
        if all(successes):
            yield state.terminated(conn)
            log.msg('Connection %s: Terminate succeeded' % conn.connection_id, system=LOG_SYSTEM)
            log.msg('Connection %s: All sub connections(%i) terminated' % (conn.connection_id, len(defs)), system=LOG_SYSTEM)
        else:
            # we are now in an inconsistent state...
            n_success = sum( [ 1 for s in successes if s ] )
            log.msg('Connection %s. Only %i of %i connections successfully terminated' % (conn.connection_id, n_success, len(defs)), system=LOG_SYSTEM)
            raise _createAggregateException(results, 'terminate', error.ConnectionError)

        defer.returnValue(connection_id)

    # --
    # Requester API
    # --

    @defer.inlineCallbacks
    def reserveConfirmed(self, header, connection_id, global_reservation_id, description, criteria):

        sub_connection = yield self.getSubConnection(header.provider_nsa, connection_id)

        # gid and desc should be identical, not checking, same with bandwidth, schedule, etc

        # check that path matches our intent

        if criteria.source_stp.network != sub_connection.source_network:
            print "source network mismatch"
        if criteria.source_stp.port    != sub_connection.source_port:
            print "source port mismatch"
        if criteria.dest_stp.network   != sub_connection.dest_network:
            print "source network mismatch"
        if criteria.dest_stp.port      != sub_connection.dest_port:
            print "source port mismatch"
        if not criteria.source_stp.labels[0].singleValue():
            print "source label is no a single value"
        if not criteria.source_stp.labels[0].singleValue():
            print "dest label is no a single value"

        # we might need something better for this...
        criteria.source_stp.labels[0].intersect(sub_connection.source_labels[0])
        criteria.dest_stp.labels[0].intersect(sub_connection.dest_labels[0])

        sub_connection.reservation_state = state.RESERVE_HELD
        sub_connection.source_labels = criteria.source_stp.labels
        sub_connection.dest_labels   = criteria.dest_stp.labels

        yield sub_connection.save()

        # figure out if we can aggregate upwards

        conn = yield sub_connection.ServiceConnection.get()
        sub_conns = yield conn.SubConnections.get()

        if sub_connection.order_id == 0:
            conn.source_labels = criteria.source_stp.labels
        if sub_connection.order_id == len(sub_conns)-1:
            conn.dest_labels = criteria.dest_stp.labels

        yield conn.save()

        if all( [ sc.reservation_state == state.RESERVE_HELD for sc in sub_conns ] ):
            log.msg('Connection %s: All sub connections reserve held, can emit reserveConfirmed' % (conn.connection_id), system=LOG_SYSTEM)
            yield state.reserveHeld(conn)
            header = nsa.NSIHeader(conn.requester_nsa, self.nsa_.urn(), None)
            # construct criteria..
            source_stp = nsa.STP(conn.source_network, conn.source_port, conn.source_labels)
            dest_stp   = nsa.STP(conn.dest_network,   conn.dest_port,   conn.dest_labels)
            criteria = nsa.ServiceParameters(conn.start_time, conn.end_time, source_stp, dest_stp, conn.bandwidth)
            self.parent_requester.reserveConfirmed(header, conn.connection_id, conn.global_reservation_id, conn.description, criteria)

        else:
            log.msg('Connection %s: Still missing reserveConfirmed messages before emitting to parent' % (conn.connection_id), system=LOG_SYSTEM)


    @defer.inlineCallbacks
    def reserveCommitConfirmed(self, header, connection_id):

        log.msg('', system=LOG_SYSTEM)
        log.msg('ReserveCommit Confirmed for sub connection %s. NSA %s ' % (connection_id, header.provider_nsa), system=LOG_SYSTEM)

        sub_connection = yield self.getSubConnection(header.provider_nsa, connection_id)
        #yield state.reserved(sub_connection)
        sub_connection.reservation_state = state.RESERVE_START
        yield sub_connection.save()

        conn = yield sub_connection.ServiceConnection.get()
        sub_conns = yield conn.SubConnections.get()

        if all( [ sc.reservation_state == state.RESERVE_START for sc in sub_conns ] ):
            yield state.reserved(conn)
            header = nsa.NSIHeader(conn.requester_nsa, self.nsa_.urn(), None)
            self.parent_requester.reserveCommitConfirmed(header, conn.connection_id)


    @defer.inlineCallbacks
    def reserveAbortConfirmed(self, header, connection_id):

        log.msg('', system=LOG_SYSTEM)
        log.msg('ReserveAbort confirmed for sub connection %s. NSA %s ' % (connection_id, header.provider_nsa), system=LOG_SYSTEM)

        sub_connection = yield self.getSubConnection(header.provider_nsa, connection_id)
        sub_connection.reservation_state = state.RESERVE_START
        yield sub_connection.save()

        conn = yield sub_connection.ServiceConnection.get()
        sub_conns = yield conn.SubConnections.get()

        if all( [ sc.reservation_state == state.RESERVE_START for sc in sub_conns ] ):
            yield state.reserved(conn)
            header = nsa.NSIHeader(conn.requester_nsa, self.nsa_.urn(), None)
            self.parent_requester.reserveAbortConfirmed(header, conn.connection_id)


    @defer.inlineCallbacks
    def provisionConfirmed(self, header, connection_id):

        log.msg('', system=LOG_SYSTEM)
        log.msg('Provision Confirmed for sub connection %s. NSA %s ' % (connection_id, header.provider_nsa), system=LOG_SYSTEM)

        sub_connection = yield self.getSubConnection(header.provider_nsa, connection_id)
        yield state.provisioned(sub_connection)
        yield sub_connection.save()

        conn = yield sub_connection.ServiceConnection.get()
        sub_conns = yield conn.SubConnections.get()

        if all( [ sc.provision_state == state.PROVISIONED for sc in sub_conns ] ):
            yield state.provisioned(conn)
            req_header = nsa.NSIHeader(conn.requester_nsa, self.nsa_.urn(), None)
            self.parent_requester.provisionConfirmed(req_header, conn.connection_id)


    @defer.inlineCallbacks
    def releaseConfirmed(self, header, connection_id):

        log.msg('', system=LOG_SYSTEM)
        log.msg('Release confirmed for sub connection %s. NSA %s ' % (connection_id, header.provider_nsa), system=LOG_SYSTEM)

        sub_connection = yield self.getSubConnection(header.provider_nsa, connection_id)
        yield state.released(sub_connection)
        yield sub_connection.save()

        conn = yield sub_connection.ServiceConnection.get()
        sub_conns = yield conn.SubConnections.get()

        if all( [ sc.provision_state == state.RELEASED for sc in sub_conns ] ):
            yield state.released(conn)
            req_header = nsa.NSIHeader(conn.requester_nsa, self.nsa_.urn(), None)
            self.parent_requester.releaseConfirmed(req_header, conn.connection_id)


    @defer.inlineCallbacks
    def terminateConfirmed(self, header, connection_id):

        sub_connection = yield self.getSubConnection(header.provider_nsa, connection_id)
        sub_connection.reservation_state = state.TERMINATED
        yield sub_connection.save()

        conn = yield sub_connection.ServiceConnection.get()
        sub_conns = yield conn.SubConnections.get()

        if all( [ sc.reservation_state == state.TERMINATED for sc in sub_conns ] ):
            yield state.terminated(conn) # we always allow, even though the canonical NSI state machine does not
            header = nsa.NSIHeader(conn.requester_nsa, self.nsa_.urn(), None)
            self.parent_requester.terminateConfirmed(header, conn.connection_id)

    # --


    def doTimeout(self, conn, timeout_value, org_connection_id, org_nsa):
        header = nsa.NSIHeader(conn.requester_nsa, self.nsa_.urn(), None)
        now = datetime.datetime.utcnow()
        self.parent_requester.reserveTimeout(header, conn.connection_id, 0, now, timeout_value, org_connection_id, org_nsa)


    def doErrorEvent(self, conn, notification_id, event, info, service_ex=None):
        header = nsa.NSIHeader(conn.requester_nsa, self.nsa_.urn(), None)
        now = datetime.datetime.utcnow()
        self.parent_requester.errorEvent(header, conn.connection_id, notification_id, now, event, info, service_ex)

    # --

    @defer.inlineCallbacks
    def findSubConnection(self, provider_nsa, connection_id):

        sub_conns_match = yield database.SubConnection.findBy(connection_id=connection_id)

        if len(sub_conns_match) == 0:
            log.msg('No subconnection with id %s found' % connection_id)
        elif len(sub_conns_match) == 1:
            defer.returnValue(sub_conns_match[0])
        else:
            log.msg('More than one subconnection with id %s found.' % connection_id)
            raise NotImplementedError('Cannot handle that situation yet, as there is no matching on NSA yet')


    @defer.inlineCallbacks
    def reserveTimeout(self, header, connection_id, notification_id, timestamp, timeout_value, org_connection_id, org_nsa):

        sub_conn = yield self.findSubConnection(header.provider_nsa, connection_id)
        conn = yield sub_conn.ServiceConnection.get()
        sub_conns = yield conn.SubConnections.get()

        if len(sub_conns) == 1:
            log.msg("reserveTimeout: One sub connection for connection %s, notifying" % conn.connection_id)
            self.doTimeout(conn, timeout_value, org_connection_id, org_nsa)
        else:
            raise NotImplementedError('Cannot handle timeout for connection with more than one sub connection')


    @defer.inlineCallbacks
    def dataPlaneStateChange(self, header, connection_id, notification_id, timestamp, dps):

        active, version, consistent = dps
        log.msg("Data plane change for sub connection: %s Active: %s, version %i, consistent: %s" % \
                 (connection_id, active, version, consistent), system=LOG_SYSTEM)

        sub_conn = yield self.findSubConnection(header.provider_nsa, connection_id)

        sub_conn.data_plane_active      = active
        sub_conn.data_plane_version     = version
        sub_conn.data_plane_consistent  = consistent

        yield sub_conn.save()

        conn = yield sub_conn.ServiceConnection.get()
        sub_conns = yield conn.SubConnections.get()

        # do notification
        aggr_active     = all( [ sc.data_plane_active     for sc in sub_conns ] )
        aggr_version    = max( [ sc.data_plane_version    for sc in sub_conns ] )
        aggr_consistent = all( [ sc.data_plane_consistent for sc in sub_conns ] )

        header = nsa.NSIHeader(conn.requester_nsa, self.nsa_.urn(), reply_to=conn.requester_url)
        now = datetime.datetime.utcnow()
        data_plane_status = (aggr_active, aggr_version, aggr_consistent)
        log.msg("Connection %s: Aggregated data plane status: Active %s, version %i, consistent %s" % \
            (conn.connection_id, aggr_active, aggr_version, aggr_consistent), system=LOG_SYSTEM)

        self.parent_requester.dataPlaneStateChange(header, conn.connection_id, 0, now, data_plane_status)


    @defer.inlineCallbacks
    def errorEvent(self, header, connection_id, notification_id, timestamp, event, info, service_ex):

        # should mark sub connection as terminated / failed
        sub_conn = yield self.findSubConnection(header.provider_nsa, connection_id)
        conn = yield sub_conn.ServiceConnection.get()
        sub_conns = yield conn.SubConnections.get()

        if len(sub_conns) == 1:
            log.msg("reserveTimeout: One sub connection for connection %s, notifying" % conn.connection_id)
            self.doErrorEvent(conn, notification_id, event, info, service_ex)
        else:
            raise NotImplementedError('Cannot handle timeout for connection with more than one sub connection')

