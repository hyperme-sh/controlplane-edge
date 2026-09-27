"""Host agent paths that skip mandatory JWT / X-Api-Key at the gateway.

The Go Host agent (locked contract) calls these with ``X-Tenant-ID`` and
either no Authorization (enroll: one-time ``enroll_token`` in the JSON
body) or ``Authorization: Bearer <device_secret>`` (``hm_dev_…``).
hypermesh-service validates those credentials via ``_require_device_auth``
and the enroll-token hash. Do not prefix-match ``/api/v1/hypermesh``.

Exact ``(method, path)`` pairs only, plus two shaped paths: job results
(UUID) and agent updates (``test`` or ``prod``). ``POST /api/v1/hypermesh/agent/tunnel/peer``
is the host WireGuard public-key post (the plane never sees the private key).
``GET /api/v1/hypermesh/agent/updates/{test|prod}`` is the signed update
relay. No prefix match.
"""

from __future__ import annotations

import uuid

# Exact (method, path) pairs. Trailing slashes are stripped by the caller.
PUBLIC_HYPERMESH_AGENT_EXACT: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/v1/hypermesh/agent/enroll"),
        ("POST", "/api/v1/hypermesh/agent/heartbeat"),
        ("GET", "/api/v1/hypermesh/agent/jobs"),
        ("POST", "/api/v1/hypermesh/agent/scorecard"),
        ("GET", "/api/v1/hypermesh/agent/tunnel"),
        ("POST", "/api/v1/hypermesh/agent/tunnel/ack"),
        ("POST", "/api/v1/hypermesh/agent/tunnel/peer"),
    }
)

_JOB_RESULT_PREFIX = "/api/v1/hypermesh/agent/jobs/"
_JOB_RESULT_SUFFIX = "/result"
_UPDATE_PREFIX = "/api/v1/hypermesh/agent/updates/"
_UPDATE_CHANNELS = frozenset({"test", "prod"})


def _is_agent_job_result(path: str) -> bool:
    """POST /api/v1/hypermesh/agent/jobs/{job_id}/result — job_id is a UUID."""

    if not path.startswith(_JOB_RESULT_PREFIX) or not path.endswith(_JOB_RESULT_SUFFIX):
        return False
    mid = path[len(_JOB_RESULT_PREFIX) : -len(_JOB_RESULT_SUFFIX)]
    if not mid or "/" in mid:
        return False
    try:
        uuid.UUID(mid)
    except ValueError:
        return False
    return True


def _is_agent_update(path: str) -> bool:
    """GET /api/v1/hypermesh/agent/updates/{test|prod} only. Not a prefix."""

    if not path.startswith(_UPDATE_PREFIX):
        return False
    return path[len(_UPDATE_PREFIX) :] in _UPDATE_CHANNELS


def is_public_hypermesh_agent(path: str, method: str = "GET") -> bool:
    """True for Host agent enroll / heartbeat / jobs / scorecard / tunnel / updates.

    Includes GET tunnel, POST tunnel/ack, POST tunnel/peer, and GET updates
    for the test and prod channels. Exact method and path only (trailing
    slash stripped). Not a prefix match.
    """

    method = method.upper()
    norm = path.rstrip("/") or "/"
    if (method, norm) in PUBLIC_HYPERMESH_AGENT_EXACT:
        return True
    if method == "GET" and _is_agent_update(norm):
        return True
    return method == "POST" and _is_agent_job_result(norm)
