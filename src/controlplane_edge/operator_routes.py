"""Explicit operator-owned payment route exceptions; absent configuration is closed."""
import json
import os
from pathlib import Path


def configured_route(kind: str, path: str, method: str | None = None) -> bool:
    filename = os.environ.get('EDGE_OPERATOR_ROUTES_FILE')
    if not filename:
        return False
    try:
        document = json.loads(Path(filename).read_text())
        if not isinstance(document, dict) or set(document) - {'public', 'retired'}:
            return False
        routes = document.get(kind, [])
        if not isinstance(routes, list):
            return False
        for route in routes:
            if not isinstance(route, dict) or set(route) != {'method', 'path'}:
                return False
            target = route['path']
            if (route['method'] != 'POST' or not isinstance(target, str)
                    or not target.startswith('/api/v1/payments/')
                    or any(value in target for value in ('?', '#', '%', '//', '..'))
                    or target.endswith('/')):
                return False
        return any(route['path'] == path and (method is None or route['method'] == method.upper()) for route in routes)
    except (OSError, ValueError, TypeError):
        return False
