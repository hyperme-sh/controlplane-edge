"""Independent admission for the declared browser API paths."""
import copy
import json
import os
from controlplane_identity.nightly import current_binding, require
from controlplane_identity.nightly_http import Authority, RunMiddleware
from controlplane_edge.device_transfer import route

CONTROL='/api/v1/internal/nightly-run'
PATHS={('GET','/auth/me'),('POST','/auth/switch-tenant'),('POST','/auth/scoped-session'),('GET','/api/v1/authority/contexts'),('GET','/api/v1/organizations')}
# The upstream owner authenticates the raw command with its independent key.
COMMANDS={('POST','/auth/nightly-run/v1/command'),('POST','/api/v1/acl/internal/nightly-run'),('POST','/api/v1/user/internal/nightly-run')}


def permitted(method,path):
    return (method,path) in PATHS or (method=='POST' and route(path) is not None)


class EdgeRunMiddleware:
    def __init__(self,app,authority):
        self.inner=RunMiddleware(app,authority,PATHS,CONTROL)

    async def __call__(self,scope,receive,send):
        inner=self.inner
        if scope['type']=='http' and permitted(scope['method'],scope['path']):
            inner=copy.copy(inner)
            inner.paths={(scope['method'],scope['path'])}
        return await inner(scope,receive,send)


def install(app):
    raw=os.environ.get('CPEDGE_NIGHTLY_RUN_CONFIG')
    if raw is None:return
    require(len(raw.encode())<=65536)
    app.add_middleware(EdgeRunMiddleware,authority=Authority(json.loads(raw),'edge'))


def forwarded_grant(request):
    binding=current_binding()
    if binding is None:return None
    require(permitted(request.method,request.url.path))
    values=request.headers.getlist('x-nightly-run-grant')
    require(len(values)==1)
    return values[0]
