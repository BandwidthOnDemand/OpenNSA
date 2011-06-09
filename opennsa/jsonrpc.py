"""
Implementation of JSON-RPC via netstrings for Twisted.

See http://json-rpc.org/ for specificiation

Author: Henrik Thostrup Jensen <htj@nordu.net>
Copyright: NORDUnet (2011)
"""

import json
import uuid

from twisted.python import log
from twisted.internet import defer
from twisted.protocols.basic import NetstringReceiver



class JSONRPCError(Exception):

    def __init__(self, error_message):
        self.error_message = error_message



class ServiceProxy(NetstringReceiver):

    def connectionMade(self):
        self.rpc_ids = {}
        self.rpc_timeouts = {}


    def call(self, method_name, *args):
        rpc_id = uuid.uuid1().hex
        data = json.dumps( {"method": method_name, 'params': args, 'id': rpc_id} )
        d = defer.Deferred()

        self.sendString(data)
        self.registerCallID(rpc_id, d)
        return d


    def registerCallID(self, rpc_id, d):
        assert rpc_id not in self.rpc_ids
        self.rpc_ids[rpc_id] = d
        # need to schedule timeout


    def stringReceived(self, string):
        try:
            response = json.loads(string)
            rpc_id = response['id']
        except ValueError, e:
            log.err('Error parsing incoming JSON payload')
        except KeyError, e:
            log.err('No id in message')

        d = self.rpc_ids.pop(rpc_id, None)
        if d is None:
            log.err('Unknown RPC id in message (%s)' % rpc_id)

        if 'error' in response:
            d.errback(response['error'])
        elif 'result' in response:
            d.callback(response['result'])
        else:
            d.errback('Invalid message response (neither error or result in payload)')


    def connectionLost(self, reason):
        # trigger all timeouts
        pass



class JSONRPCService(NetstringReceiver):

    def __init__(self):
        self.functions = {}


    def registerFunction(self, name, func):
        self.functions[name] = func


    def errorReply(self, rpc_id, error_msg):

        message = json.dumps( { 'id': rpc_id, 'error': error_msg } )
        self.sendString(message)

    def reply(self, rpc_id, result):

        message = json.dumps( { 'id': rpc_id, 'result': result } )
        self.sendString(message)


    def stringReceived(self, string):

        try:
            request = json.loads(string)
            rpc_id = request['id']
        except ValueError, e:
            log.msg('Error parsing JSON RPC payload (invalid JSON)')
        except KeyError, e:
            log.msg('No RPC id in JSON RPC message')

        try:
            method_name = request['method']
            method_args = request['params']
        except KeyError, e:
            log.msg('Missing method information, cannot dispatch')
            self.errorReply(rpc_id, 'Missing method information')

        try:
            f = self.functions[method_name]
        except KeyError:
            self.errorReply(rpc_id, 'No such method (%s)' % method_name)

        try:
            result = f(*method_args)
        except Exception, e:
            self.errorReply(rpc_id, str(e))

        # FIXME handle serialization fail
        self.reply(rpc_id, result)


