"""
TwistedSUDS client.

Author: Henrik Thostrup Jensen <htj _at_ nordu.net>
Copyright: NORDUnet (2011)

Licsense: MIT License (same as Twisted)
"""

import os
import urlparse
import StringIO

from twisted.python import log
from twisted.internet import reactor, defer
from twisted.web import client as twclient
from twisted.internet.error import ConnectionDone

from suds.transport import Transport, TransportError
from suds.options import Options
from suds.reader import DefinitionsReader
from suds.wsdl import Definitions
from suds.client import Factory



class FileTransport(Transport):
    """
    File-only transport to plug into SUDS.

    Using this guaranties non-blocking behaviour, but at the expense of not
    supporting stuff imported via http.
    """
    def __init__(self):
        Transport.__init__(self)


    def open(self, request):

        parsed_url = urlparse.urlparse(request.url)
        if parsed_url.scheme != 'file':
            raise TransportError('FileTransport does not support %s as protocol' % parsed_url.scheme, 0)

        path = parsed_url.path
        if not os.path.exists(path):
            raise TransportError('Requested file %s does not exist' % path, None, None)

        # make file object in memory so file cannot be changed
        data = open(path).read()
        return StringIO.StringIO(data)


    def send(self, _):
        raise NotImplementedError('Send not supported in FileTransport.')



class TwistedSUDSClient:

    def __init__(self, wsdl): #, service_url):

        self.options = Options()
        self.options.transport = FileTransport()

        reader = DefinitionsReader(self.options, Definitions)

        self.wsdl = reader.open(wsdl)
        self.type_factory = Factory(self.wsdl)

#        self.service_url = service_url


    def createType(self, type_name):
        """
        @args typename: type to create. QNames are specified with {namespace}element syntax.
        """
        return self.type_factory.create(type_name)


    def invoke(self, url, method_name, *args):
        """
        Invoke a SOAP/WSDL action. No getattr/getitem magic, sorry.

        @args url: URL/Endpoint to POST SOAP at.
        @args method_name: Method to invoke.
        @args *args Argument for method.
        """
        def invokeError(err):
            if isinstance(err.value, ConnectionDone):
                pass # these are pretty common when the remote shuts down
            else:
                return log.err(err)

        method = self._getMethod(method_name)

        # build envelope and get action
        soap_envelope = method.binding.input.get_message(method, args, {})
        soap_envelope = soap_envelope.str().encode('utf-8')
        soap_action = str(method.soap.action)

        # dispatch
        d, factory = self._httpRequest(url, soap_action, soap_envelope)
        d.addCallback(self._parseResponse, factory, method)
        d.addErrback(invokeError)
        return d


    def _getMethod(self, method_name):
        # one service and port should be enough for everybody
        assert len(self.wsdl.services) == 1
        service = self.wsdl.services[0]

        assert len(service.ports) == 1
        port = service.ports[0]

        # print port.methods.keys()
        method = port.methods[method_name]
        return method


    def _httpRequest(self, url, soap_action, soap_envelope):
        # copied from twisted.web.client in order to get access to the
        # factory (which contains response codes, headers, etc)

        if type(url) is not str:
            e = ValueError('URL must be string, not %s' % type(url))
            return defer.fail(e), None

        scheme, host, port, _ = twclient._parse(url)

        factory = twclient.HTTPClientFactory(url, method='POST', postdata=soap_envelope)
        factory.noisy = False # stop spewing about factory start/stop

        # fix missing port in header (bug in twisted.web.client)
        if port:
            factory.headers['host'] = host + ':' + str(port)

        factory.headers['soapaction'] = soap_action

        if scheme == 'https':
            raise NotImplementedError('https currently not supported')
            reactor.connectSSL(host, port, factory, ctxFactory)
        else:
            reactor.connectTCP(host, port, factory)

        return factory.deferred, factory


    def _parseResponse(self, response, factory, method):

        if factory.status == '200':
            _, result = method.binding.input.get_reply(method, response)
            return result

        else:
            raise NotImplementedError('non-200 error handling not implemented')

