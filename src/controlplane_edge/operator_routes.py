"""Explicit operator-owned payment route exceptions; absent configuration is closed."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re


@dataclass(frozen=True)
class SignedDelivery:
    signature_header: str
    max_body_bytes: int


def _routes(kind: str) -> list[dict]:
    filename = os.environ.get('EDGE_OPERATOR_ROUTES_FILE')
    inline = os.environ.get('EDGE_OPERATOR_ROUTES_JSON')
    if bool(filename) == bool(inline):
        return []
    try:
        document = json.loads(Path(filename).read_text() if filename else inline)
        if not isinstance(document, dict) or set(document) - {'public', 'retired', 'signed'}:
            return []
        routes = document.get(kind, [])
        if not isinstance(routes, list):
            return []
        fields = {'method', 'path'}
        if kind == 'signed':
            fields |= {'signature_header', 'max_body_bytes'}
        for route in routes:
            if not isinstance(route, dict) or set(route) != fields:
                return []
            target = route['path']
            if (route['method'] != 'POST' or not isinstance(target, str)
                    or not target.startswith('/api/v1/payments/')
                    or any(value in target for value in ('?', '#', '%', '//', '..'))
                    or target.endswith('/')):
                return []
            if kind == 'signed':
                header, limit = route['signature_header'], route['max_body_bytes']
                if (not isinstance(header, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}-signature', header)
                        or type(limit) is not int or not 1 <= limit <= (1 << 20)):
                    return []
        return routes
    except (OSError, ValueError, TypeError):
        return []


def configured_route(kind: str, path: str, method: str | None = None) -> bool:
    return any(
        route['path'] == path and (method is None or route['method'] == method.upper())
        for route in _routes(kind)
    )


def signed_delivery(path: str, method: str) -> SignedDelivery | None:
    if method != 'POST':
        return None
    matches = [route for route in _routes('signed') if route['path'] == path]
    if len(matches) != 1:
        return None
    return SignedDelivery(matches[0]['signature_header'], matches[0]['max_body_bytes'])
