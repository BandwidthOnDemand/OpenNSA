"""
Web Service protocol for OpenNSA.

Author: Henrik Thostrup Jensen <htj@nordu.net>
Copyright: NORDUnet (2011)
"""

import uuid

from twisted.python import log

from opennsa.protocols.webservice.ext import twistedsuds


WSDL_PROVIDER   = 'file:///home/htj/nsi/opennsa/wsdl/ogf_nsi_connection_provider_v1_0.wsdl'
WSDL_REQUESTER  = 'file:///home/htj/nsi/opennsa/wsdl/ogf_nsi_connection_requester_v1_0.wsdl'



def createCorrelationId():
    return str(uuid.uuid1().int)


class ProviderClient:

    def __init__(self, reply_to):

        self.reply_to = reply_to
        self.client = twistedsuds.TwistedSUDSClient(WSDL_PROVIDER)


    def _createGenericRequestType(self, requester_nsa, provider_nsa, connection_id):

        req = self.client.createType('{http://schemas.ogf.org/nsi/2011/07/connection/types}GenericRequestType')
        req.requesterNSA = requester_nsa.uri()
        req.providerNSA  = provider_nsa.uri()
        req.connectionId = connection_id
        return req


    def reservation(self, correlation_id, requester_nsa, provider_nsa, session_security_attr, global_reservation_id, description, connection_id, service_parameters):

        #correlation_id = self._createCorrelationId()

        res_req = self.client.createType('{http://schemas.ogf.org/nsi/2011/07/connection/types}ReservationType')

        res_req.requesterNSA                = requester_nsa.uri()
        res_req.providerNSA                 = provider_nsa.uri()

        res_req.reservation.globalReservationId     = global_reservation_id
        res_req.reservation.description             = description
        res_req.reservation.connectionId            = connection_id

        res_req.reservation.path.directionality     = service_parameters.directionality
        res_req.reservation.path.sourceSTP.stpId    = service_parameters.source_stp.uri()
        #res_req.reservation.path.sourceSTP.stpSpecAttrs.guaranteed = ['123' ]
        #res_req.reservation.path.sourceSTP.stpSpecAttrs.preferred =  ['abc', 'def']
        res_req.reservation.path.destSTP.stpId      = service_parameters.dest_stp.uri()

        res_req.reservation.serviceParameters.schedule.startTime    = service_parameters.start_time
        res_req.reservation.serviceParameters.schedule.endTime      = service_parameters.end_time
        res_req.reservation.serviceParameters.bandwidth.desired     = service_parameters.bandwidth_desired
        res_req.reservation.serviceParameters.bandwidth.minimum     = service_parameters.bandwidth_minimum
        res_req.reservation.serviceParameters.bandwidth.maximum     = service_parameters.bandwidth_maximum
        #res_req.reservation.serviceParameters.serviceAttributes.guaranteed = [ '1a' ]
        #res_req.reservation.serviceParameters.serviceAttributes.preferred  = [ '2c', '3d' ]

        d = self.client.invoke(provider_nsa.uri(), 'reservation', correlation_id, self.reply_to, res_req)
        return d


    def provision(self, correlation_id, requester_nsa, provider_nsa, session_security_attr, connection_id):

        req = self._createGenericRequestType(requester_nsa, provider_nsa, connection_id)
        d = self.client.invoke(provider_nsa.uri(), 'provision', correlation_id, self.reply_to, req)
        return d


    def release(self, correlation_id, requester_nsa, provider_nsa, session_security_attr, connection_id):

        req = self._createGenericRequestType(requester_nsa, provider_nsa, connection_id)
        d = self.client.invoke(provider_nsa.uri(), 'release', correlation_id, self.reply_to, req)
        return d


    def terminate(self, correlation_id, requester_nsa, provider_nsa, session_security_attr, connection_id):

        req = self._createGenericRequestType(requester_nsa, provider_nsa, connection_id)
        d = self.client.invoke(provider_nsa.uri(), 'terminate', correlation_id, self.reply_to, req)
        return d


    def query(self, correlation_id, requester_nsa, provider_nsa, session_security_attr, operation="Summary", connection_ids=None, global_reservation_ids=None):

        correlation_id = self._createCorrelationId()
        req = self.client.createType('{http://schemas.ogf.org/nsi/2011/07/connection/types}QueryType')
        #print req

        req.requesterNSA = requester_nsa.uri()
        req.providerNSA  = provider_nsa.uri()
        req.operation = operation
        req.queryFilter.connectionId = connection_ids or []
        req.queryFilter.globalReservationId = global_reservation_ids or []
        #print req

        d = self.client.invoke(provider_nsa.uri(), 'query', correlation_id, self.reply_to, req)
        return d




class RequesterClient:

    def __init__(self):

        self.client = twistedsuds.TwistedSUDSClient(WSDL_REQUESTER)


    def _createGenericConfirmType(self, requester_nsa, provider_nsa, global_reservation_id, connection_id):

        conf = self.client.createType('{http://schemas.ogf.org/nsi/2011/07/connection/types}GenericConfirmedType')
        conf.requesterNSA        = requester_nsa.uri()
        conf.providerNSA         = provider_nsa.uri()
        conf.globalReservationId = global_reservation_id
        conf.connectionId        = connection_id
        return conf


    def reservationConfirmed(self, requester_uri, correlation_id, requester_nsa, provider_nsa, global_reservation_id, description, connection_id, service_parameters):

        #correlation_id = self._createCorrelationId()

        res_conf = self.client.createType('{http://schemas.ogf.org/nsi/2011/07/connection/types}ReservationConfirmedType')

        res_conf.requesterNSA   = requester_nsa.uri()
        res_conf.providerNSA    = provider_nsa.uri()

        res_conf.reservation.globalReservationId    = global_reservation_id
        res_conf.reservation.description            = description
        res_conf.reservation.connectionId           = connection_id

        d = self.client.invoke(requester_uri, 'reservationConfirmed', correlation_id, res_conf)
        return d


    def reservationFailed(self, requester_nsa, provider_nsa, global_reservation_id, connection_id, connection_state, service_exception):
        raise NotImplementedError('NSI WS protocol under development')



    def provisionConfirmed(self, requester_uri, correlation_id, requester_nsa, provider_nsa, global_reservation_id, connection_id):

        conf = self._createGenericConfirmType(requester_nsa, provider_nsa, global_reservation_id, connection_id)
        d = self.client.invoke(requester_uri, 'provisionConfirmed', correlation_id, conf)
        return d

    #def provisionFailed(self, 


    def releaseConfirmed(self, requester_uri, correlation_id, requester_nsa, provider_nsa, global_reservation_id, connection_id):

        conf = self._createGenericConfirmType(requester_nsa, provider_nsa, global_reservation_id, connection_id)
        d = self.client.invoke(requester_uri, 'releaseConfirmed', correlation_id, conf)
        return d

    #def releaseFailed(self, 


    def terminateConfirmed(self, requester_uri, correlation_id, requester_nsa, provider_nsa, global_reservation_id, connection_id):

        conf = self._createGenericConfirmType(requester_nsa, provider_nsa, global_reservation_id, connection_id)
        d = self.client.invoke(requester_uri, 'terminateConfirmed', correlation_id, conf)
        return d

    #def terminateFailed(self, 



