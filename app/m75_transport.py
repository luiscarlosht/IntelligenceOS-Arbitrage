"""M75 fixed first-page transport. Existing TLS primitive; no SDK or refresh loop."""
from copy import deepcopy
from app.m72_transport import PilotTransport
from app.m75_policy import requests


class Transport(PilotTransport):
    @staticmethod
    def scope(slot: int):
        if type(slot) is not int or not 1<=slot<=21:raise ValueError('Exactly 21 possible request slots')
        return ('authentication',{}) if slot==1 else ('keyword',deepcopy(requests()[slot-2]['parameters']))

    def validate_slot(self,request,slot: int):
        super().validate_slot(request,slot)
        expected={'content-type'} if slot==1 else {'x-amz-access-token'}
        if {k.casefold() for k,_ in request.header_items()}!=expected or request.unredirected_hdrs:
            raise ValueError('No extra authentication, host or cookie headers permitted')

    def accept_authentication(self,body: dict):
        super().accept_authentication(body)
        if any(not c.isascii() or not c.isprintable() or c.isspace() for c in self._access):
            raise ValueError('Printable nonwhitespace ASCII bearer token required')
