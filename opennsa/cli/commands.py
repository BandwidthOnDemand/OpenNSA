# cli commands

from twisted.python import log
from twisted.internet import defer

from opennsa import constants as cnt, nsa, error



def _createSTP(stp_arg):

    # no generic label stuff for now
    if '#' in stp_arg:
        stp_desc, vlan = stp_arg.split('#')
        network, port = stp_desc.rsplit(':',1)
        label = nsa.Label(cnt.ETHERNET_VLAN, vlan)
    else:
        network, port = stp_arg.rsplit(':',1)
        label = None

    return nsa.STP(network, port, label)


def _createP2PS(src, dst, capacity):

    src_stp = _createSTP(src)
    dst_stp = _createSTP(dst)

    return nsa.Point2PointService(src_stp, dst_stp, capacity)


def _handleEvent(event):

    notification_type, header, entry = event

    if notification_type == 'errorEvent':
        log.msg('Error event: %s' % str(entry))
        return True
    elif notification_type == 'dataPlaneStateChange':
        cid, nid, timestamp, dps = entry
        active, version, consistent = dps
        if active:
            log.msg('Connection %s Data plane active, version %i, consistent: %s' % (cid, version, consistent))
            return False
        else:
            log.msg('Connection %s Data plane down, version %i, consistent: %s' % (cid, version, consistent))
            return consistent # this means we don't exit on initial partially down, where we are not consistent

    else:
        log.msg('Unrecognized event %s ' % notification_type)
        return False


def _logError(e):

    error_type = e.__class__.__name__
    variables = '. Variables: ' + ' '.join ( [ ': '.join(tvp) for tvp in e.variables ] ) if e.variables else ''
    log.msg('Error: %s: %s%s' % (error_type, str(e), variables))



@defer.inlineCallbacks
def discover(client, service_url):

    res = yield client.queryNSA(service_url)
    print "-- COMMAND RESULT --"
    print res
    print "--"


@defer.inlineCallbacks
def reserveonly(client, nsi_header, src, dst, start_time, end_time, capacity, connection_id, global_id):

    schedule = nsa.Schedule(start_time, end_time)
    service_def = _createP2PS(src, dst, capacity)
    crt = nsa.Criteria(0, schedule, service_def)

    try:
        connection_id, _,_,criteria  = yield client.reserve(nsi_header, connection_id, global_id, 'Test Connection', crt)
        sd = criteria.service_def[0]
        log.msg("Connection created and held. Id %s at %s" % (connection_id, nsi_header.provider_nsa))
        log.msg("Source - Destination: %s - %s" % (sd.source_stp, sd.dest_stp))

    except error.NSIError, e:
        _logError(e)


@defer.inlineCallbacks
def reserve(client, nsi_header, src, dst, start_time, end_time, capacity, connection_id, global_id):

    schedule = nsa.Schedule(start_time, end_time)
    service_def = _createP2PS(src, dst, capacity)
    crt = nsa.Criteria(0, schedule, service_def)

    try:
        connection_id, global_reservation_id, description, criteria = yield client.reserve(nsi_header, connection_id, global_id, 'Test Connection', crt)
        sd = criteria.service_def
        log.msg("Connection created and held. Id %s at %s" % (connection_id, nsi_header.provider_nsa))
        log.msg("Source - Destination: %s - %s" % (sd.source_stp, sd.dest_stp))

        nsi_header.newCorrelationId()
        yield client.reserveCommit(nsi_header, connection_id)
        log.msg("Reservation committed at %s" % nsi_header.provider_nsa)

    except error.NSIError, e:
        _logError(e)


@defer.inlineCallbacks
def reserveprovision(client, nsi_header, src, dst, start_time, end_time, capacity, connection_id, global_id, notification_wait):

    schedule = nsa.Schedule(start_time, end_time)
    service_def = _createP2PS(src, dst, capacity)
    crt = nsa.Criteria(0, schedule, service_def)

    try:
        connection_id, _,_, criteria = yield client.reserve(nsi_header, connection_id, global_id, 'Test Connection', crt)
        sd = criteria.service_def
        log.msg("Connection created and held. Id %s at %s" % (connection_id, nsi_header.provider_nsa))
        log.msg("Source - Destination: %s - %s" % (sd.source_stp, sd.dest_stp))

        nsi_header.newCorrelationId()
        yield client.reserveCommit(nsi_header, connection_id)
        log.msg("Connection committed at %s" % nsi_header.provider_nsa)

        # query
        nsi_header.newCorrelationId()
        qr = yield client.querySummary(nsi_header, connection_ids=[connection_id] )
        print "Query result:", qr

        # provision
        nsi_header.newCorrelationId()
        yield client.provision(nsi_header, connection_id)
        log.msg('Connection %s provisioned' % connection_id)

        while notification_wait:
            event = yield client.notifications.get()
            exit = _handleEvent(event)
            if exit:
                break

    except error.NSIError, e:
        _logError(e)



@defer.inlineCallbacks
def rprt(client, nsi_header, src, dst, start_time, end_time, capacity, connection_id, global_id):
    # reserve, provision, release,  terminate
    schedule = nsa.Schedule(start_time, end_time)
    service_def = _createP2PS(src, dst, capacity)
    crt = nsa.Criteria(0, schedule, service_def)

    try:
        connection_id, _,_, criteria = yield client.reserve(nsi_header, connection_id, global_id, 'Test Connection', crt)
        sd = criteria.service_def
        log.msg("Connection created and held. Id %s at %s" % (connection_id, nsi_header.provider_nsa))
        log.msg("Source - Destination: %s - %s" % (sd.source_stp, sd.dest_stp))

        # commit
        nsi_header.newCorrelationId()
        yield client.reserveCommit(nsi_header, connection_id)
        log.msg("Connection committed at %s" % nsi_header.provider_nsa)

        # provision
        nsi_header.newCorrelationId()
        yield client.provision(nsi_header, connection_id)
        log.msg('Connection %s provisioned' % connection_id)

        # release
        nsi_header.newCorrelationId()
        yield client.release(nsi_header, connection_id)
        log.msg('Connection %s released' % connection_id)

        # terminate
        nsi_header.newCorrelationId()
        yield client.terminate(nsi_header, connection_id)
        log.msg('Connection %s terminated' % connection_id)

    except error.NSIError, e:
        _logError(e)


@defer.inlineCallbacks
def reservecommit(client, nsi_header, connection_id):

    try:
        yield client.reserveCommit(nsi_header, connection_id)
        log.msg("Reservation committed at %s" % nsi_header.provider_nsa)

    except error.NSIError, e:
        _logError(e)


@defer.inlineCallbacks
def provision(client, nsi_header, connection_id, notification_wait):

    try:
        yield client.provision(nsi_header, connection_id)
        log.msg('Connection %s provisioned' % connection_id)
    except error.NSIError, e:
        _logError(e)

    if notification_wait:
        log.msg("Notification wait not added to provision yet")


@defer.inlineCallbacks
def release(client, nsi_header, connection_id, notification_wait):

    try:
        yield client.release(nsi_header, connection_id)
        log.msg('Connection %s released' % connection_id)
    except error.NSIError, e:
        _logError(e)

    if notification_wait:
        log.msg("Notification wait not added to release yet")


@defer.inlineCallbacks
def terminate(client, nsi_header, connection_id):

    try:
        yield client.terminate(nsi_header, connection_id)
        log.msg('Connection %s terminated' % connection_id)
    except error.NSIError, e:
        _logError(e)


@defer.inlineCallbacks
def querysummary(client, nsi_header, connection_ids, global_reservation_ids):

    try:
        qc = yield client.querySummary(nsi_header, connection_ids, global_reservation_ids)
        log.msg('Query results:')
        for qr in qc:
            cid, gid, desc, crits, requester, states, children = qr
            dps = states[3]
            log.msg('Connection    : %s' % cid)
            if gid:
                log.msg('  Global ID   : %s' % gid)
            if desc:
                log.msg('  Description : %s' % desc)

            if crits:
                crit = crits[0]
                log.msg('  Start time  : %s, End time: %s' % (crit.schedule.start_time, crit.schedule.end_time))
                if type(crit.service_def) is nsa.Point2PointService:
                    sd = crit.service_def
                    log.msg('  Source STP  : %s' % sd.source_stp)
                    log.msg('  Dest   STP  : %s' % sd.dest_stp)
                    log.msg('  Bandwidth   : %s' % sd.capacity)
                    log.msg('  Direction   : %s' % sd.directionality)
                    log.msg('  Symmetric   : %s' % sd.symmetric)
                    log.msg('  Params      : %s' % sd.parameters)
                else:
                    log.msg('  Unrecognized service definition: %s' % str(crit.service_def))

            log.msg('  States      : %s' % ', '.join(states[0:3]))
            log.msg('  Dataplane   : Active : %s, Version: %s, Consistent %s' % dps)

            if children:
                log.msg('  Children    : %s' % children)
    except error.NSIError, e:
        _logError(e)


@defer.inlineCallbacks
def querydetails(client, nsi_header, connection_ids, global_reservation_ids):

    try:
        qc = yield client.queryDetails(nsi_header, connection_ids, global_reservation_ids)
        log.msg('Query results:')
        for qr in qc:
            log.msg('Connection: %s' % qr.connectionId)
            log.msg('  States: %s' % qr.connectionStates)
    except error.NSIError, e:
        _logError(e)


def path(topology_file, source_stp, dest_stp):

    raise NotImplementedError('Path computation not available for NML yet')
    topo = None

    source_network, source_port = source_stp.split(':',1)
    dest_network,   dest_port   = dest_stp.split(':', 1)

    r_source_stp    = nsa.STP(source_network, source_port)
    r_dest_stp      = nsa.STP(dest_network,   dest_port)

    paths = topo.findPaths(r_source_stp, r_dest_stp)

    for p in sorted(paths, key=lambda p : len(p.network_links)):
        log.msg(str(p))


def topology(topology_file):

    raise NotImplementedError('Topology dump not available for NML yet')
    topo = None

    for nw in topo.networks:
        ns = '%s (%s)' % (nw.name, ','.join( sorted( [ ep.endpoint for ep in nw.endpoints ] ) ) )
        log.msg(ns)


def topologyGraph(topology_file, all_links=False):

    raise NotImplementedError('Topology graph not available for NML yet')
    topo = None

    links = []

    for nw in topo.networks:
        for ep in nw.endpoints:
            if ep.dest_stp:
                nw1 = nw.name.replace('.ets', '').replace('-','_')
                nw2 = ep.dest_stp.network.replace('.ets', '').replace('-', '_')

                l = [ nw1, nw2 ]
                if all_links:
                    if nw1 < nw2: # this prevents us from building double links
                        links.append(l)
                else:
                    l = sorted(l)
                    if not l in links:
                        links.append(l)

    log.msg('graph Network {')
    for l in sorted(links):
        log.msg('  %s -- %s;' % (l[0], l[1]))
    log.msg('}')

