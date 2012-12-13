"""
Web Service protocol for OpenNSA.

Author: Henrik Thostrup Jensen <htj@nordu.net>
Copyright: NORDUnet (2011)
"""

from opennsa.protocols.shared import minisoap, httpclient
from opennsa.protocols.nsi2 import actions, connectiontypes as CT, headertypes as HT, helper



def utcTime(dt):
    return dt.isoformat().rsplit('.',1)[0] + 'Z'



class ProviderClient:

    def __init__(self, ctx_factory=None):

        self.ctx_factory = ctx_factory


    def _genericConfirm(self, requester_url, action, correlation_id, requester_nsa, provider_nsa, global_reservation_id, connection_id):

        header = HT.CommonHeaderType(helper.PROTO, correlation_id, requester_nsa, provider_nsa)
        generic_confirm = CT.GenericConfirmedType(global_reservation_id, connection_id)

        header_payload = helper.export(header,          helper.FRAMEWORK_TYPES_NS)
        body_payload   = helper.export(generic_confirm, helper.CONNECTION_TYPES_NS)

        payload = minisoap.createSoapPayload(body_payload, header_payload)

        def gotReply(data):
            print "GC REPLY\n", data

        f = httpclient.httpRequest(requester_url, action, payload, ctx_factory=self.ctx_factory)
        f.deferred.addCallbacks(gotReply) #, errReply)
        return f.deferred


    def reserveConfirmed(self, requester_url, correlation_id, requester_nsa, provider_nsa, global_reservation_id, description, connection_id, service_parameters):

        sp = service_parameters
        s_stp = sp.source_stp
        d_stp = sp.dest_stp

        header = HT.CommonHeaderType(None, correlation_id, requester_nsa, provider_nsa)

        version = 0
        schedule = CT.ScheduleType( sp.start_time.isoformat(), sp.end_time.isoformat() )
        bandwidth = sp.bandwidth

        service_attrs = None

        source_stp = CT.StpType(s_stp.network, s_stp.endpoint, None, 'Ingress')
        dest_stp   = CT.StpType(d_stp.network, d_stp.endpoint, None, 'Egress')

        path = CT.PathType(sp.directionality, False, source_stp, dest_stp)

        criteria = CT.ReservationConfirmCriteriaType(version, schedule, bandwidth, service_attrs, path)

        reserve_conf = CT.ReserveConfirmedType(global_reservation_id, description, connection_id, [ criteria ] )

        header_payload = helper.export(header,       helper.FRAMEWORK_TYPES_NS)
        body_payload   = helper.export(reserve_conf, helper.CONNECTION_TYPES_NS)

        payload = minisoap.createSoapPayload(body_payload, header_payload)

        print "PAYLOAD\n", payload

        def gotReply(data):
            print "REPLY\n", data
            return ""

        print "--\n", requester_url
        f = httpclient.httpRequest(requester_url, actions.RESERVE_CONFIRMED, payload, ctx_factory=self.ctx_factory)
        f.deferred.addCallbacks(gotReply) #, errReply)
        return f.deferred

#
#    def reserveFailed(self, requester_url, correlation_id, requester_nsa, provider_nsa, global_reservation_id, connection_id, connection_state, error_msg):
#
#        res_fail = self.client.createType('{http://schemas.ogf.org/nsi/2011/10/connection/types}GenericFailedType')
#        nsi_ex   = self.client.createType('{http://schemas.ogf.org/nsi/2011/10/connection/types}ServiceExceptionType')
#
#        res_fail.requesterNSA   = requester_nsa
#        res_fail.providerNSA    = provider_nsa
#
#        res_fail.globalReservationId    = global_reservation_id
#        res_fail.connectionId           = connection_id
#        res_fail.connectionState        = connection_state
#
#        nsi_ex.errorId = 'RESERVATION_FAILURE'
#        nsi_ex.text = error_msg
#        res_fail.serviceException = nsi_ex
#
#        d = self.client.invoke(requester_url, 'reserveFailed', correlation_id, res_fail)
#        return d
#

    def provisionConfirmed(self, requester_url, correlation_id, requester_nsa, provider_nsa, global_reservation_id, connection_id):

        return self._genericConfirm(requester_url, actions.PROVISION_CONFIRMED, correlation_id, requester_nsa, provider_nsa, global_reservation_id, connection_id)


#    def provisionFailed(self, requester_url, correlation_id, requester_nsa, provider_nsa, global_reservation_id, connection_id, connection_state, error_msg):
#
#        gft = self.client.createType('{http://schemas.ogf.org/nsi/2011/10/connection/types}GenericFailedType')
#        net = self.client.createType('{http://schemas.ogf.org/nsi/2011/10/connection/types}ServiceExceptionType')
#
#        gft.requesterNSA   = requester_nsa
#        gft.providerNSA    = provider_nsa
#
#        gft.globalReservationId    = global_reservation_id
#        gft.connectionId           = connection_id
#        gft.connectionState        = connection_state
#
#        net.errorId = 'PROVISION_FAILURE'
#        net.text = error_msg
#        gft.serviceException = net
#
#        d = self.client.invoke(requester_url, 'provisionFailed', correlation_id, gft)
#        return d


    def releaseConfirmed(self, requester_url, correlation_id, requester_nsa, provider_nsa, global_reservation_id, connection_id):

        return self._genericConfirm(requester_url, actions.RELEASE_CONFIRMED, correlation_id, requester_nsa, provider_nsa,
                                    global_reservation_id, connection_id)

#    def releaseFailed(self, requester_url, correlation_id, requester_nsa, provider_nsa, global_reservation_id, connection_id, connection_state, error_msg):
#
#        gft = self.client.createType('{http://schemas.ogf.org/nsi/2011/10/connection/types}GenericFailedType')
#        net = self.client.createType('{http://schemas.ogf.org/nsi/2011/10/connection/types}ServiceExceptionType')
#
#        gft.requesterNSA   = requester_nsa
#        gft.providerNSA    = provider_nsa
#
#        gft.globalReservationId    = global_reservation_id
#        gft.connectionId           = connection_id
#        gft.connectionState        = connection_state
#
#        net.errorId = 'RELEASE_FAILURE'
#        net.text = error_msg
#        gft.serviceException = net
#
#        d = self.client.invoke(requester_url, 'releaseFailed', correlation_id, gft)
#        return d
#

    def terminateConfirmed(self, requester_url, correlation_id, requester_nsa, provider_nsa, global_reservation_id, connection_id):

        return self._genericConfirm(requester_url, actions.TERMINATE_CONFIRMED, correlation_id, requester_nsa, provider_nsa,
                                    global_reservation_id, connection_id)


#    def terminateFailed(self, requester_url, correlation_id, requester_nsa, provider_nsa, global_reservation_id, connection_id, connection_state, error_msg):
#
#        gft = self.client.createType('{http://schemas.ogf.org/nsi/2011/10/connection/types}GenericFailedType')
#        net = self.client.createType('{http://schemas.ogf.org/nsi/2011/10/connection/types}ServiceExceptionType')
#
#        gft.requesterNSA   = requester_nsa
#        gft.providerNSA    = provider_nsa
#
#        gft.globalReservationId    = global_reservation_id
#        gft.connectionId           = connection_id
#        gft.connectionState        = connection_state
#
#        net.errorId = 'TERMINATE_FAILURE'
#        net.text = error_msg
#        gft.serviceException = net
#
#        d = self.client.invoke(requester_url, 'terminateFailed', correlation_id, gft)
#        return d
#
#
#    def queryConfirmed(self, requester_url, correlation_id, requester_nsa, provider_nsa, operation, connections):
#
#        res = self.client.createType('{http://schemas.ogf.org/nsi/2011/10/connection/types}QueryConfirmedType')
#        res.requesterNSA = requester_nsa
#        res.providerNSA  = provider_nsa
#
#        if operation == "Summary":
#            qsrs = []
#            for conn in connections:
#                qsr = self.client.createType('{http://schemas.ogf.org/nsi/2011/10/connection/types}QuerySummaryResultType')
#                #print qsr
#                qsr.globalReservationId = conn.global_reservation_id
#                qsr.description         = conn.description
#                qsr.connectionId        = conn.connection_id
#                qsr.connectionState     = conn.state()
#
#                qsr.path.sourceSTP.stpId    = conn.source_stp.urn()
#                qsr.path.destSTP.stpId      = conn.dest_stp.urn()
#
#                qsr.serviceParameters.schedule.startTime = utcTime(conn.service_parameters.start_time)
#                qsr.serviceParameters.schedule.endTime   = utcTime(conn.service_parameters.end_time)
#
#                qsr.serviceParameters.bandwidth.desired  = conn.service_parameters.bandwidth.desired
#                qsr.serviceParameters.bandwidth.minimum  = conn.service_parameters.bandwidth.minimum
#                qsr.serviceParameters.bandwidth.maximum  = conn.service_parameters.bandwidth.maximum
#
#                def createOrderedSTP(stp, rank):
#                    ostp = self.client.createType('{http://schemas.ogf.org/nsi/2011/10/connection/types}OrderedServiceTerminationPointType')
#                    ostp.stpId = stp.urn()
#                    ostp._order = rank
#                    return ostp
#
#                # create list of all stps, but skip source and dest stp
#                stps = [ stp for sc in conn.connections() for stp in sc.stps() ] [1:-1]
#                for i, stp in zip(range(len(stps)), stps):
#                    qsr.path.stpList.stp.append( createOrderedSTP(stp, i) )
#
#                qsrs.append(qsr)
#
#            res.reservationSummary = qsrs
#
#        elif operation == "Details":
#            qdr = self.client.createType('{http://schemas.ogf.org/nsi/2011/10/connection/types}QueryDetailsResultType')
#            #print qdr
#            qdr.globalReservationId = '123'
#            res.reservationDetails = [ qdr ]
#
#        else:
#            raise ValueError('Invalid query operation type')
#
#        d = self.client.invoke(requester_url, 'queryConfirmed', correlation_id, res)
#        return d
#
#
#    def queryFailed(self, requester_url, correlation_id, requester_nsa, provider_nsa, error_msg):
#
#        print "CLIENT QUERY FAILED"
#        qft = self.client.createType('{http://schemas.ogf.org/nsi/2011/10/connection/types}QueryFailedType')
#        net = self.client.createType('{http://schemas.ogf.org/nsi/2011/10/connection/types}ServiceExceptionType')
#
#        qft.requesterNSA = requester_nsa
#        qft.providerNSA  = provider_nsa
#
#        net.errorId = 'QUERY_FAILURE'
#        net.text = error_msg
#        qft.serviceException = net
#
#        d = self.client.invoke(requester_url, 'queryFailed', correlation_id, qft)
#        return d

