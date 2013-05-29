import os, datetime, json

from twisted.trial import unittest
from twisted.internet import reactor, defer, task

from opennsa import nsa, registry, database, error, state
from opennsa.topology import nml
from opennsa.backends import dud



class DUDBackendTest(unittest.TestCase):

    def setUp(self):

        self.clock = task.Clock()

        self.sr = registry.ServiceRegistry()
        self.registry_system = 'dud-test'
        self.backend = dud.DUDNSIBackend('Test', self.sr, self.registry_system)
        self.backend.scheduler.clock = self.clock

        self.backend.startService()

        tcf = os.path.expanduser('~/.opennsa-test.json')
        tc = json.load( open(tcf) )
        database.setupDatabase( tc['database'], tc['database-user'], tc['database-password'])

        self.requester_nsa = nsa.NetworkServiceAgent('test-requester', 'http://example.org/nsa-test-requester')
        self.provider_nsa  = nsa.NetworkServiceAgent('test-provider',  'http://example.org/nsa-test-provider')

        source_stp  = nsa.STP('Aruba', 'A1', labels=[ nsa.Label(nml.ETHERNET_VLAN, '1-2') ] )
        dest_stp    = nsa.STP('Aruba', 'A3', labels=[ nsa.Label(nml.ETHERNET_VLAN, '2-3') ] )
        start_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=2)
        end_time   = datetime.datetime.utcnow() + datetime.timedelta(seconds=10)
        bandwidth = 200
        self.service_params = nsa.ServiceParameters(start_time, end_time, source_stp, dest_stp, bandwidth)

        # just so we don't have to put them in the test code
        self.reserve        = self.sr.getHandler(registry.RESERVE,        registry.NSI2_LOCAL)
        self.reserveCommit  = self.sr.getHandler(registry.RESERVE_COMMIT, registry.NSI2_LOCAL)
        self.reserveAbort   = self.sr.getHandler(registry.RESERVE_ABORT,  registry.NSI2_LOCAL)
        self.provision      = self.sr.getHandler(registry.PROVISION,      registry.NSI2_LOCAL)
        self.release        = self.sr.getHandler(registry.RELEASE,        registry.NSI2_LOCAL)
        self.terminate      = self.sr.getHandler(registry.TERMINATE,      registry.NSI2_LOCAL)


    @defer.inlineCallbacks
    def tearDown(self):
        from opennsa.backends.common import simplebackend
        # delete all created connections from test database
        yield simplebackend.Simplebackendconnection.deleteAll()
        yield self.backend.stopService()


    @defer.inlineCallbacks
    def testBasicUsage(self):

        cid,_,_,_ = yield self.reserve(self.requester_nsa, self.provider_nsa, None, None, None, None, self.service_params)
        yield self.terminate(self.requester_nsa, self.provider_nsa, None, cid)


    @defer.inlineCallbacks
    def testProvisionPostTerminate(self):

        cid,_,_,_ = yield self.reserve(self.requester_nsa, self.provider_nsa, None, None, None, None, self.service_params)
        yield self.reserveCommit(self.requester_nsa, self.provider_nsa, None, cid)
        yield self.terminate(self.requester_nsa, self.provider_nsa, None, cid)
        try:
            yield self.provision(self.requester_nsa, self.provider_nsa, None, cid)
            self.fail('Should have raised ConnectionGoneError')
        except error.ConnectionGoneError:
            pass # expected


    @defer.inlineCallbacks
    def testProvisionUsage(self):

        cid,_,_,_ = yield self.reserve(self.requester_nsa, self.provider_nsa, None, None, None, None, self.service_params)
        yield self.reserveCommit(self.requester_nsa, self.provider_nsa, None, cid)
        yield self.provision(self.requester_nsa, self.provider_nsa, None, cid)
        yield self.terminate(self.requester_nsa, self.provider_nsa, None, cid)


    @defer.inlineCallbacks
    def testProvisionReleaseUsage(self):

        d_up   = defer.Deferred()
        d_down = defer.Deferred()

        def dataPlaneChange(requester_nsa, provider_nsa, session_security_attr, connection_id, dps, timestamp):
            active, version, version_consistent = dps
            if active:
                d_up.callback(connection_id)
            else:
                d_down.callback(connection_id)

        self.sr.registerEventHandler(registry.DATA_PLANE_CHANGE,  dataPlaneChange, self.registry_system)

        cid,_,_,sp = yield self.reserve(self.requester_nsa, self.provider_nsa, None, None, None, None, self.service_params)
        yield self.reserveCommit(self.requester_nsa, self.provider_nsa, None, cid)

        yield self.provision(self.requester_nsa, self.provider_nsa, None, cid)
        self.clock.advance(3)
        yield d_up
        yield self.release(  self.requester_nsa, self.provider_nsa, None, cid)
        yield d_down
        yield self.terminate(self.requester_nsa, self.provider_nsa, None, cid)


    @defer.inlineCallbacks
    def testDoubleReserve(self):

        cid,_,_,_ = yield self.reserve(self.requester_nsa, self.provider_nsa, None, None, None, None, self.service_params)
        try:
            cid,_,_,_ = yield self.reserve(self.requester_nsa, self.provider_nsa, None, None, None, None, self.service_params)
            self.fail('Should have raised STPUnavailableError')
        except error.STPUnavailableError:
            pass # we expect this


    @defer.inlineCallbacks
    def testProvisionNonExistentConnection(self):

        try:
            yield self.provision(self.requester_nsa, self.provider_nsa, None, '1234')
            self.fail('Should have raised ConnectionNonExistentError')
        except error.ConnectionNonExistentError:
            pass # expected


    @defer.inlineCallbacks
    def testActivation(self):

        d_up = defer.Deferred()

        def dataPlaneChange(requester_nsa, provider_nsa, session_security_attr, connection_id, dps, timestamp):
            active, version, version_consistent = dps
            if active:
                values = connection_id, active, version_consistent, version, timestamp
                d_up.callback(values)

        self.sr.registerEventHandler(registry.DATA_PLANE_CHANGE,  dataPlaneChange, self.registry_system)

        cid,_,_,_ = yield self.reserve(self.requester_nsa, self.provider_nsa, None, None, None, None, self.service_params)
        yield self.reserveCommit(self.requester_nsa, self.provider_nsa, None, cid)
        yield self.provision(self.requester_nsa, self.provider_nsa, None, cid)
        self.clock.advance(3)
        connection_id, active, version_consistent, version, timestamp = yield d_up
        self.failUnlessEqual(cid, connection_id)
        self.failUnlessEqual(active, True)
        self.failUnlessEqual(version_consistent, True)

        #yield self.release(  None, self.provider_nsa, None, cid)
        yield self.terminate(self.requester_nsa, self.provider_nsa, None, cid)


    @defer.inlineCallbacks
    def testReserveAbort(self):

        # these need to be constructed such that there is only one label option
        source_stp  = nsa.STP('Aruba', 'A1', labels=[ nsa.Label(nml.ETHERNET_VLAN, '2') ] )
        dest_stp    = nsa.STP('Aruba', 'A3', labels=[ nsa.Label(nml.ETHERNET_VLAN, '2') ] )
        start_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=1)
        end_time   = datetime.datetime.utcnow() + datetime.timedelta(seconds=10)
        service_params = nsa.ServiceParameters(start_time, end_time, source_stp, dest_stp, 200)

        cid,_,_,_ = yield self.reserve(self.requester_nsa, self.provider_nsa, None, None, None, None, service_params)
        yield self.reserveAbort(self.requester_nsa, self.provider_nsa, None, cid)
        # try to reserve the same resources
        cid,_,_,_ = yield self.reserve(self.requester_nsa, self.provider_nsa, None, None, None, None, service_params)


    @defer.inlineCallbacks
    def testReserveTimeout(self):

        # these need to be constructed such that there is only one label option
        source_stp  = nsa.STP('Aruba', 'A1', labels=[ nsa.Label(nml.ETHERNET_VLAN, '2') ] )
        dest_stp    = nsa.STP('Aruba', 'A3', labels=[ nsa.Label(nml.ETHERNET_VLAN, '2') ] )
        start_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=1)
        end_time   = datetime.datetime.utcnow() + datetime.timedelta(seconds=60)
        service_params = nsa.ServiceParameters(start_time, end_time, source_stp, dest_stp, 200)

        d = defer.Deferred()
        def reserveTimeout(requester_nsa, provider_nsa, session_security_attr, connection_id, connection_states, timeout_value, timestamp):
            values = connection_id, connection_states, timeout_value, timestamp
            d.callback(values)

        self.sr.registerEventHandler(registry.RESERVE_TIMEOUT,  reserveTimeout, self.registry_system)

        cid,_,_,_ = yield self.reserve(self.requester_nsa, self.provider_nsa, None, None, None, None, service_params)

        self.clock.advance(dud.DUDNSIBackend.TPC_TIMEOUT + 1)
        connection_id, connection_states, timeout_value, timestamp = yield d
        rsm, psm, lsm, asm = connection_states

        self.failUnlessEquals(connection_id, cid)
        self.failUnlessEquals(rsm, state.RESERVED)

        # try to reserve the same resources
        cid,_,_,_ = yield self.reserve(self.requester_nsa, self.provider_nsa, None, None, None, None, service_params)


    @defer.inlineCallbacks
    def testSlowActivate(self):
        # key here is that end time is passed when activation is done

        source_stp  = nsa.STP('Aruba', 'A1', labels=[ nsa.Label(nml.ETHERNET_VLAN, '100') ] )
        dest_stp    = nsa.STP('Aruba', 'A3', labels=[ nsa.Label(nml.ETHERNET_VLAN, '100') ] )
        start_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=1)
        end_time   = datetime.datetime.utcnow() + datetime.timedelta(seconds=2)
        service_params = nsa.ServiceParameters(start_time, end_time, source_stp, dest_stp, 200)

        d_up = defer.Deferred()
        d_down = defer.Deferred()

        def dataPlaneChange(requester_nsa, provider_nsa, session_security_attr, connection_id, dps, timestamp):
            active, version, version_consistent = dps
            values = connection_id, active, version_consistent, version, timestamp
            if active:
                d_up.callback(values)
            else:
                d_down.callback(values)

        self.sr.registerEventHandler(registry.DATA_PLANE_CHANGE,  dataPlaneChange, self.registry_system)

        def setupLink(connection_id, src, dst, bandwidth):
            d = defer.Deferred()
            reactor.callLater(2, d.callback, None)
            return d

        # make actication fail via monkey patching
        self.backend.connection_manager.setupLink = setupLink

        cid,_,_,_ = yield self.reserve(self.requester_nsa, self.provider_nsa, None, None, None, None, service_params)
        yield self.reserveCommit(self.requester_nsa, self.provider_nsa, None, cid)
        yield self.provision(self.requester_nsa, self.provider_nsa, None, cid)

        self.clock.advance(2)
        connection_id, active, version_consistent, version, timestamp = yield d_up
        self.failUnlessEqual(cid, connection_id)
        self.failUnlessEqual(active, True)
        self.failUnlessEqual(version_consistent, True)

        self.clock.advance(2)
        connection_id, active, version_consistent, version, timestamp = yield d_down
        self.failUnlessEqual(cid, connection_id)
        self.failUnlessEqual(active, False)

        yield self.terminate(self.requester_nsa, self.provider_nsa, None, cid)

    testSlowActivate.skip = 'Uses reactor calls and real timings, and is too slow to be a regular test'


    @defer.inlineCallbacks
    def testFaultyActivate(self):

        d_err = defer.Deferred()

        def errorEvent(requester_nsa, provider_nsa, session_security_attr, connection_id, event, connection_states, timestamp, info, ex):
            d_err.callback( (event, connection_id, connection_states, timestamp, info, ex) )

        self.sr.registerEventHandler(registry.ERROR_EVENT, errorEvent, self.registry_system)

        # make actication fail via monkey patching
        self.backend.connection_manager.setupLink = \
            lambda src, dst : defer.fail(error.InternalNRMError('Link setup failed'))

        cid,_,_,_ = yield self.reserve(self.requester_nsa, self.provider_nsa, None, None, None, None, self.service_params)
        yield self.reserveCommit(self.requester_nsa, self.provider_nsa, None, cid)
        yield self.provision(self.requester_nsa, self.provider_nsa, None, cid)
        self.clock.advance(3)
        vals = yield d_err

        event, connection_id, connection_states, timestamp, info, ex = vals
        self.failUnlessEquals(event, 'activateFailed')
        self.failUnlessEquals(connection_id, cid)


    @defer.inlineCallbacks
    def testFaultyDeactivate(self):

        d_up  = defer.Deferred()
        d_err = defer.Deferred()

        def dataPlaneChange(requester_nsa, provider_nsa, session_security_attr, connection_id, dps, timestamp):
            active, version, version_consistent = dps
            if active:
                d_up.callback( ( connection_id, active, version_consistent, version, timestamp ) )

        def errorEvent(requester_nsa, provider_nsa, session_security_attr, connection_id, event, connection_states, timestamp, info, ex):
            d_err.callback( (event, connection_id, connection_states, timestamp, info, ex) )

        self.sr.registerEventHandler(registry.DATA_PLANE_CHANGE,  dataPlaneChange, self.registry_system)
        self.sr.registerEventHandler(registry.ERROR_EVENT, errorEvent, self.registry_system)

        # make actication fail via monkey patching
        self.backend.connection_manager.teardownLink = \
            lambda src, dst : defer.fail(error.InternalNRMError('Link teardown failed'))

        cid,_,_,_ = yield self.reserve(self.requester_nsa, self.provider_nsa, None, None, None, None, self.service_params)
        yield self.reserveCommit(self.requester_nsa, self.provider_nsa, None, cid)
        yield self.provision(self.requester_nsa, self.provider_nsa, None, cid)

        self.clock.advance(3)
        yield d_up

        self.clock.advance(11)
        yield d_err

