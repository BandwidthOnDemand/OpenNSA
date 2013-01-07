"""
High-level functionality for creating clients and services in OpenNSA.
"""

from twisted.python import log
from twisted.web import resource, server
from twisted.application import internet, service as twistedservice

from opennsa import config, logging, registry, nsiservice, viewresource
from opennsa.topology import gole
from opennsa.protocols import nsi1, nsi2, discovery



def setupBackend(backend_conf, network_name):

    for backend_name, cfg in backend_conf.items():
        backend_type = cfg['_backend_type']
        bc = cfg.copy()
        del bc['_backend_type']

        if backend_type == config.BLOCK_DUD:
            from opennsa.backends import dud
            return dud.DUDNSIBackend(network_name)

        elif backend_type == config.BLOCK_JUNOS:
            from opennsa.backends import junos
            return junos.JunOSBackend(network_name, bc.items())

        elif backend_type == config.BLOCK_FORCE10:
            from opennsa.backends import force10
            return force10.Force10Backend(network_name, bc.items())

        elif backend_type == config.BLOCK_ARGIA:
            from opennsa.backends import argia
            return argia.ArgiaBackend(network_name, bc.items())

        elif backend_type == config.BLOCK_BROCADE:
            from opennsa.backends import brocade
            return brocade.BrocadeBackend(network_name, bc.items())



class OpenNSAService(twistedservice.MultiService):

    def __init__(self, vc):
        twistedservice.MultiService.__init__(self)
        self.vc = vc


    def startService(self):
        """
        This sets up the OpenNSA service and ties together everything in the initialization.
        There are a lot of things going on, but none of it it particular deep.
        """
        log.msg('OpenNSA service initializing')

        vc = self.vc

        topology_sources = [ open(tf) for tf in vc[config.TOPOLOGY_FILE] ]

        topology, _ = gole.parseTopology(topology_sources, open(vc[config.NRM_MAP_FILE]) if vc[config.NRM_MAP_FILE] else None )

        if vc[config.HOST] is None:
            import socket
            vc[config.HOST] = socket.getfqdn()

        ctx_factory = None
        if vc[config.TLS]:
            from opennsa import ctxfactory
            ctx_factory = ctxfactory.ContextFactory(vc[config.KEY], vc[config.CERTIFICATE], vc[config.CERTIFICATE_DIR], vc[config.VERIFY_CERT])

        backend = setupBackend(vc['backend'], vc[config.NETWORK_NAME])

        top_resource = resource.Resource()
        service_registry = registry.ServiceRegistry()
        nsi_service  = nsiservice.NSIService(vc[config.NETWORK_NAME], backend, service_registry, topology)

        discovery.setupDiscoveryService(None, top_resource)

        nsi1.setupProvider(nsi_service, top_resource, service_registry, vc[config.HOST], vc[config.PORT], vc[config.WSDL_DIRECTORY])

        nsi2.setupProvider(nsi_service, top_resource, service_registry, vc[config.HOST], vc[config.PORT])

        vr = viewresource.ConnectionListResource(nsi_service)
        top_resource.children['NSI'].putChild('connections', vr)

        factory = server.Site(top_resource, logPath='/dev/null')


        if vc[config.TLS]:
            internet.SSLServer(vc[config.PORT], factory, ctx_factory).setServiceParent(self)
        else:
            internet.TCPServer(vc[config.PORT], factory).setServiceParent(self)

        # do not start sub-services until we have started this one
        twistedservice.MultiService.startService(self)

        log.msg('OpenNSA service started')


    def stopService(self):
        twistedservice.Service.stopService(self)



def createApplication(config_file=config.DEFAULT_CONFIG_FILE, debug=False):

    application = twistedservice.Application('OpenNSA')

    try:

        cfg = config.readConfig(config_file)
        vc = config.readVerifyConfig(cfg)

        # if log file is empty string use stdout
        if vc[config.LOG_FILE]:
            log_file = open(vc[config.LOG_FILE], 'a')
        else:
            import sys
            log_file = sys.stdout

        nsa_service = OpenNSAService(vc)
        nsa_service.setServiceParent(application)

        application.setComponent(log.ILogObserver, logging.DebugLogObserver(log_file, debug).emit)
        return application

    except config.ConfigurationError as e:
        import sys
        sys.stderr.write("Configuration error: %s\n" % e)
        sys.exit(1)

