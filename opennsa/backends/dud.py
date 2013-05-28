"""
NRM backends which just logs actions performed.

Author: Henrik Thostrup Jensen <htj@nordu.net>
Copyright: NORDUnet (2011)
"""

import string
import random

from twisted.python import log
from twisted.internet import defer

from opennsa.backends.common import simplebackend



class DUDNSIBackend(simplebackend.SimpleBackend):

    def __init__(self, network_name, service_registry, parent_system):

        name = 'DUD NRM %s' % network_name
        cm = DUDConnectionManager(name)
        simplebackend.SimpleBackend.__init__(self, network_name, cm, service_registry, parent_system, name)



class DUDConnectionManager:

    def __init__(self, log_system):
        self.log_system = log_system


    def getResource(self, port, label_type, label_value):
        return port


    def getTarget(self, port, label_type, label_value):
        return port + '#' + label_value


    def createConnectionId(self, source_target, dest_target):
        return 'DUD-' + ''.join( [ random.choice(string.hexdigits[:16]) for _ in range(8) ] )


    def canSwapLabel(self, label_type):
        #return True
        return False


    def setupLink(self, connection_id, source_target, dest_target, bandwidth):
        log.msg('Link %s -> %s up' % (source_target, dest_target), system=self.log_system)
        return defer.succeed(None)
        #from opennsa import error
        #return defer.fail(error.InternalNRMError('Link setup failed'))


    def teardownLink(self, connection_id, source_target, dest_target, bandwidth):
        log.msg('Link %s -> %s down' % (source_target, dest_target), system=self.log_system)
        return defer.succeed(None)
        #from opennsa import error
        #return defer.fail(error.InternalNRMError('Link teardown failed'))

