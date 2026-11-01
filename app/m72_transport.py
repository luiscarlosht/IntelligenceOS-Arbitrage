"""M72-only one-shot TLS transport; production construction is authorization-gated."""
from app.m71_adapter import CatalogTransport, parameters
from app.m71_manifest import queries


class PilotTransport(CatalogTransport):
    def __init__(self,credentials: dict,*,seller_id: str | None=None):
        super().__init__(credentials)
        self._seller_id=seller_id

    def secrets(self):
        return super().secrets()|({self._seller_id} if self._seller_id else set())

    def clear(self):
        super().clear();self._seller_id=None

    def build_slot(self,slot: int):
        phase,params=self.scope(slot)
        return self.build(phase,params)

    @staticmethod
    def scope(slot: int):
        if type(slot) is not int or not 1<=slot<=10:raise ValueError('Ten fixed request slots required')
        return ('authentication',{}) if slot==1 else ('keyword',parameters(queries()[slot-2]))

    def validate_slot(self,request,slot: int):
        phase,params=self.scope(slot)
        self.validate(request,phase,params)

    def accept_authentication(self,body: dict):
        if str(body.get('token_type','')).casefold()!='bearer':raise ValueError('Bearer token contract required')
        super().accept_authentication(body)
        if '\r' in self._access or '\n' in self._access or len(self._access)>2048:raise ValueError('Invalid private token')

    def send_slot(self,request,slot: int):
        self.validate_slot(request,slot)
        # Existing primitive: verified TLS, no proxy, redirects, retries or SDK
        # refresh; 10-second socket timeout and bounded response body.
        from app.amazon_pilot import _request_json
        reply=_request_json(request)
        return dict(status=getattr(reply,'http_status',None),headers=getattr(reply,'rate_headers',{}),body=dict(reply))
