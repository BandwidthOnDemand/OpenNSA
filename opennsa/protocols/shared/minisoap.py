"""
Various SOAP stuff to use when SUDS is broken.

Author: Henrik Thostrup Jensen <htj@nordu.net>
Copyright: NORDUnet (2011-2012)
"""

from xml.etree import cElementTree as ET


LOG_SYSTEM = 'opennsa.protocols.soap'

SOAP_ENVELOPE_NS        = "http://schemas.xmlsoap.org/soap/envelope/"

SOAP_ENV                = ET.QName("{%s}Envelope"   % SOAP_ENVELOPE_NS)
SOAP_HEADER             = ET.QName("{%s}Header"     % SOAP_ENVELOPE_NS)
SOAP_BODY               = ET.QName("{%s}Body"       % SOAP_ENVELOPE_NS)
SOAP_FAULT              = ET.QName("{%s}Fault"      % SOAP_ENVELOPE_NS)


ET.register_namespace('soap', SOAP_ENVELOPE_NS)


def _indent(elem, level=0):
    i = "\n" + level*"   "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "   "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            _indent(elem, level+1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i



def createSoapEnvelope():

    envelope = ET.Element(SOAP_ENV)
    header = ET.SubElement(envelope, SOAP_HEADER)
    body = ET.SubElement(envelope, SOAP_BODY)

    return envelope, header, body



def createSoapPayload(body_payload=None, header_payload=None):
    # somewhat backwards, but it works

    envelope, header, body = createSoapEnvelope()

    if header_payload is not None:
        header_content = ET.fromstring(header_payload)
        header.append(header_content)

    if body_payload is not None:
        body_content = ET.fromstring(body_payload)
        body.append(body_content)

    _indent(envelope)
    payload = ET.tostring(envelope, 'utf-8')

    return payload



def parseSoapPayload(payload):

    envelope = ET.fromstring(payload)

    assert envelope.tag == SOAP_ENV, 'Top element in soap payload is not SOAP:Envelope'

    header_elements = None

    for ec in envelope:
        if ec.tag == SOAP_HEADER:
            if header_elements is not None:
                raise ValueError('SOAP Payload has multiple header elements')
            header_elements = list(ec)
            continue
        elif ec.tag == SOAP_BODY:
            return header_elements, list(ec)
        else:
            raise ValueError('Invalid entry in SOAP payload: %s' % (ec.tag))

    raise ValueError('SOAP Payload does not have a body')


def parseFault(payload):

    envelope = ET.fromstring(payload)

    if envelope.tag != SOAP_ENV:
        raise ValueError('Top element in soap payload is not SOAP:Envelope')

    # no header parsing for now

    body = envelope.find( str(SOAP_BODY) )
    if body is None:
        raise ValueError('Fault payload has no SOAP:Body element in SOAP:Envelope')

    fault = body.find( str(SOAP_FAULT) )
    if fault is None:
        raise ValueError('Fault payload has no SOAP:Fault element in SOAP:Body')

    # only SOAP 1.1 for now
    fault_code = fault.find('faultcode')
    if fault_code is None:
        raise ValueError('Fault payload has no faultcode element in SOAP:Fault')

    fault_string = fault.find('faultstring')
    if fault_string is None:
        raise ValueError('Fault payload has no faultstring element in SOAP:Fault')

    detail = None

    dt = fault.find('detail')
    if dt is not None:
        dc = dt.getchildren()[0]
        if dc is not None:
            detail = ET.tostring(dc)

    return fault_code.text, fault_string.text, detail




