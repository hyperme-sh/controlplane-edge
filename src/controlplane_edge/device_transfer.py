"""Narrow owner-authenticated pairing proxy; no key or session authority here."""
import asyncio
from contextlib import nullcontext
import json
import logging
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import anyio
import httpx
from starlette.requests import Request
from starlette.responses import Response
from controlplane_edge.aggregation_settings import OpenAPIAggregationSettings
from controlplane_edge.edge_settings import GatewayCrossCuttingSettings

RELAY = '/auth/sea-device-link/v1'
ACL = '/api/v1/acl/sociacl/device-transfer'
BODY_TIMEOUT = 3
SEND_TIMEOUT = 3
SCOPES = {'sourceOrigin', 'destinationOrigin', 'application', 'tenant', 'audience'}
ACTIONS = {'sender': {'admit', 'join', 'send', 'completed', 'cancel'},
           'receiver': {'create', 'offer', 'receive', 'complete', 'completed', 'cancel'}}
PRIVATE = {'Cache-Control': 'private, no-store', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'}


def protected(path):
    return any(path == p or path.startswith(p + '/') for p in (RELAY, ACL))


def route(path):
    match = re.fullmatch(RELAY + r'/sessions/([A-Za-z0-9_-]{43})/([a-z]+)', path)
    if match and match[2] in ACTIONS['sender'] | ACTIONS['receiver']:
        return 'auth', match[2]
    if path in (ACL + '/state', ACL + '/current'):
        return 'acl', path.rsplit('/', 1)[1]
    return None


def load_scopes():
    path = os.environ.get('CPEDGE_DEVICE_TRANSFER_SCOPES_FILE')
    if not path:
        return []
    raw = Path(path).read_bytes()
    if len(raw) > 32768:
        raise ValueError('Pairing configuration too large')
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {'version', 'scopes'} or value['version'] != 1 or not isinstance(value['scopes'], list) or not 1 <= len(value['scopes']) <= 8:
        raise ValueError('Invalid pairing configuration')
    for scope in value['scopes']:
        if not isinstance(scope, dict) or set(scope) != SCOPES or not all(isinstance(s, str) and 0 < len(s) <= 512 for s in scope.values()):
            raise ValueError('Invalid pairing scope')
        for key in ('sourceOrigin', 'destinationOrigin'):
            u = urlsplit(scope[key])
            if u.scheme != 'https' or not u.hostname or u.username or u.password or u.path or u.query or u.fragment:
                raise ValueError('Invalid pairing origin')
    return value['scopes']


class PairingLogFilter(logging.Filter):
    def filter(self, record):
        if any(p in record.getMessage() for p in (RELAY, ACL)):
            if record.name == 'uvicorn.access' and isinstance(record.args, tuple) and len(record.args) == 5:
                args = list(record.args)
                args[2] = '/device-transfer/[redacted]'
                record.args = tuple(args)
            else:
                record.msg, record.args = 'Device transfer request [redacted]', ()
        return True


class DeviceTransferMiddleware:
    def __init__(self, app):
        self.app = app
        self.enabled = GatewayCrossCuttingSettings().edge_proxy_enabled
        self.scopes = load_scopes()
        self.settings = OpenAPIAggregationSettings()
        self.capacity = anyio.CapacityLimiter(8)
        self.buckets = {}
        self.active_clients = {}
        for name in ('uvicorn.access', 'httpx'):
            logger = logging.getLogger(name)
            if not any(isinstance(f, PairingLogFilter) for f in logger.filters):
                logger.addFilter(PairingLogFilter())

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not protected(scope['path']):
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        status, body, headers = 503, b'', dict(PRIVATE)
        acquired = False
        try:
            try:
                minute = int(time.monotonic() // 60)
                self.buckets = {key: val for key, val in self.buckets.items() if val[0] == minute}
                client = (scope.get('client') or ('unknown', 0))[0]
                count = self.buckets.get(client, (minute, 0))[1]
                if self.active_clients.get(client, 0) >= 2 or count >= 120 or (client not in self.buckets and len(self.buckets) >= 1024):
                    status = 429
                else:
                    self.buckets[client] = (minute, count + 1)
                    self.capacity.acquire_nowait()
                    acquired = True
                    self.active_clients[client] = self.active_clients.get(client, 0) + 1
                    async with asyncio.timeout(12):
                        status, body, extra = await self.forward(request)
                        headers.update(extra)
            except anyio.WouldBlock:
                status = 429
            except (ValueError, TypeError, KeyError, RecursionError):
                status = 400
            except (TimeoutError, httpx.HTTPError):
                status = 503
            try:
                async with asyncio.timeout(SEND_TIMEOUT):
                    await Response(body, status_code=status, headers=headers)(scope, receive, send)
            except TimeoutError:
                # A stalled reader must not retain a buffered owner response.
                return
        finally:
            if acquired:
                self.capacity.release()
                self.active_clients[client] -= 1
                if not self.active_clients[client]:
                    del self.active_clients[client]

    async def forward(self, request):
        selected = route(request.url.path)
        if not self.enabled or selected is None or not self.scopes:
            return 404, b'', {}
        if request.url.query or request.scope.get('raw_path', b'').decode('ascii', errors='replace') != request.url.path:
            return 400, b'', {}
        origin = request.headers.get('origin')
        if request.headers.getlist('origin') != [origin] or origin not in {s[k] for s in self.scopes for k in ('sourceOrigin', 'destinationOrigin')}:
            return 403, b'', {}
        cors = {'Access-Control-Allow-Origin': origin, 'Vary': 'Origin'}
        if request.method == 'OPTIONS':
            if request.headers.get('access-control-request-method') != 'POST':
                return 405, b'', cors
            return 204, b'', {**cors, 'Access-Control-Allow-Methods': 'POST', 'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Tenant-ID, X-Pairing-Role, X-Pairing-Capability, X-Pairing-Join'}
        if request.method != 'POST':
            return 405, b'', cors
        if request.headers.get('content-type', '').split(';')[0] != 'application/json' or request.headers.getlist('content-encoding'):
            return 415, b'', cors
        owner, action = selected
        maximum = 710000 if owner == 'auth' else 4096
        lengths = request.headers.getlist('content-length')
        if lengths and (len(lengths) != 1 or not re.fullmatch('[0-9]{1,9}', lengths[0])):
            return 400, b'', cors
        if lengths and int(lengths[0]) > maximum:
            return 413, b'', cors
        data = bytearray()
        async with asyncio.timeout(BODY_TIMEOUT):
            async for chunk in request.stream():
                if len(data) + len(chunk) > maximum:
                    return 413, b'', cors
                data.extend(chunk)
        if lengths and len(data) != int(lengths[0]):
            return 400, b'', cors
        value = json.loads(data)
        if not isinstance(value, dict):
            return 400, b'', cors
        binding = value.get('binding')
        candidate = value.get('scope') if owner == 'auth' or action == 'state' else (binding.get('scope') if isinstance(binding, dict) else None)
        if candidate not in self.scopes:
            return 403, b'', cors
        outgoing = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Origin': origin}
        role = request.headers.get('x-pairing-role') if owner == 'auth' else 'sender'
        if owner == 'auth':
            if role not in ACTIONS or action not in ACTIONS[role]:
                return 403, b'', cors
            for key in ('x-pairing-role', 'x-pairing-capability') + (('x-pairing-join',) if action == 'join' else ()):
                values = request.headers.getlist(key)
                if len(values) != 1 or (key != 'x-pairing-role' and not re.fullmatch('[A-Za-z0-9_-]{43}', values[0])):
                    return 400, b'', cors
                outgoing[key] = values[0]
        if origin != candidate['destinationOrigin' if role == 'receiver' else 'sourceOrigin']:
            return 403, b'', cors
        if role != 'receiver':
            token = request.headers.get('authorization', '')
            if request.headers.getlist('authorization') != [token] or not re.fullmatch(r'Bearer [A-Za-z0-9._~-]{1,8192}', token) or request.headers.getlist('x-tenant-id') not in ([candidate['tenant']], []) or (owner == 'acl' and not request.headers.getlist('x-tenant-id')):
                return 401, b'', cors
            outgoing.update({'Authorization': token, 'X-Tenant-ID': candidate['tenant']})
        # Each owner authenticates person/scope or receiver capability. No API-key
        # exchange, host credential, browser cookie or forwarded client IP here.
        base = getattr(self.settings, owner + '_service_url')
        if not base:
            return 503, b'', cors
        try:
            from opentelemetry.instrumentation.utils import suppress_instrumentation
            quiet = suppress_instrumentation()
        except ImportError:
            quiet = nullcontext()
        with quiet:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
                async with client.stream('POST', str(base).rstrip('/') + request.url.path, content=bytes(data), headers=outgoing) as response:
                    if 300 <= response.status_code < 400:
                        return 502, b'', cors
                    output = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(output) + len(chunk) > (710000 if owner == 'auth' else 4 * 1024 * 1024):
                            return 502, b'', cors
                        output.extend(chunk)
                    if response.headers.get('content-type', '').split(';')[0] != 'application/json':
                        return 502, b'', cors
                    return response.status_code, bytes(output), {**cors, 'Content-Type': 'application/json'}
