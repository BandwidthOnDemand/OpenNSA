# cli commands

import uuid
import random
import time
import datetime

from twisted.python import log
from twisted.internet import defer

from opennsa import nsa



@defer.inlineCallbacks
def reserve(client, requester_url, service_url, topology_file, network, provider_nsa, requester_nsa, source_stp, dest_stp):

    client_nsa      = nsa.NetworkServiceAgent(requester_nsa, requester_url)
    provider_nsa    = nsa.NetworkServiceAgent(provider_nsa, service_url)

    source_network, source_port = source_stp.split(':',1)
    dest_network, dest_port     = dest_stp.split(':', 1)

    r_source_stp    = nsa.STP(source_network, source_port)
    r_dest_stp      = nsa.STP(dest_network,   dest_port)

    # all this needs to be settable
    start_time = datetime.datetime.utcfromtimestamp(time.time() + 2 )
    end_time   = datetime.datetime.utcfromtimestamp(time.time() + 60 )
    bwp = nsa.BandwidthParameters(1000)
    service_params  = nsa.ServiceParameters(start_time, end_time, r_source_stp, r_dest_stp, bandwidth=bwp)
    global_id       = 'urn:uuid:' + str(uuid.uuid1())
    connection_id   = 'conn-%i' % random.randrange(1000,9999)

    log.msg("Connection ID: %s" % connection_id)
    log.msg("Global ID: %s" % global_id)

    r = yield client.reserve(client_nsa, provider_nsa, None, global_id, 'Test Connection', connection_id, service_params)
    print "Reservation created. Connection ID:", connection_id


@defer.inlineCallbacks
def provision(wsdl_dir, service_url, provider_nsa, requester_nsa, source_stp, dest_stp):

    pass



@defer.inlineCallbacks
def release():

    pass



@defer.inlineCallbacks
def terminate():

    pass




@defer.inlineCallbacks
def querysummary():

    pass


@defer.inlineCallbacks
def querydetails():

    raise NotImplementedError('QueryDetails command not implemented')

