"""The edge proxy forwards a response body as it arrives.

A buffering proxy deadlocks these tests rather than failing an assertion: the
upstream withholds its last chunk until the caller has received the first, so
nothing completes unless the body is streamed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from controlplane_edge.edge_proxy import EdgeProxyMiddleware

# The hypermesh gateway is deliberately not an edge prefix, so the streaming
# case through this proxy is ai-service completion.
CHAT_PATH = "/api/v1/ai/complete"


def _app(handler) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        EdgeProxyMiddleware,
        settings=SimpleNamespace(ai_service_url="http://ai.test"),
        cross=SimpleNamespace(edge_proxy_enabled=True, proxy_timeout_s=5.0),
    )
    app.state.edge_proxy_client = AsyncClient(transport=httpx.MockTransport(handler))
    return app


async def _drive(app, path: str, body: bytes = b"{}"):
    """Drive the ASGI app directly and yield the messages it sends.

    httpx's ASGITransport runs the app to completion before returning a
    response, so it cannot observe incremental delivery. A real server relays
    each http.response.body message as it is produced, which is what this
    reproduces.
    """

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"test"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("1.2.3.4", 1234),
        "server": ("test", 80),
    }
    sent: asyncio.Queue = asyncio.Queue()
    request_sent = False
    disconnected = asyncio.Event()

    async def receive():
        # Body once, then quiet. StreamingResponse also polls this waiting for
        # http.disconnect, and returning the request again trips Starlette.
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        await sent.put(message)

    task = asyncio.create_task(app(scope, receive, send))
    return task, sent


@pytest.mark.asyncio
async def test_body_reaches_the_caller_before_the_upstream_finishes() -> None:
    release = asyncio.Event()

    async def upstream_body():
        yield b'data: {"choices":[{"delta":{"content":"tok1"}}]}\n\n'
        await release.wait()
        yield b'data: {"choices":[{"delta":{"content":"tok2"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=upstream_body(),
        )

    task, sent = await _drive(_app(handler), CHAT_PATH)

    start = await asyncio.wait_for(sent.get(), timeout=5)
    assert start["type"] == "http.response.start"
    assert start["status"] == 200
    assert (b"content-type", b"text/event-stream") in start["headers"]

    # Times out if the proxy buffers: the upstream cannot finish until release
    # is set, and release is only set once the first chunk has arrived.
    first = await asyncio.wait_for(sent.get(), timeout=5)
    assert first["type"] == "http.response.body"
    assert b"tok1" in first["body"]
    assert first.get("more_body") is True
    assert not release.is_set()

    release.set()
    rest = b""
    while True:
        message = await asyncio.wait_for(sent.get(), timeout=5)
        rest += message.get("body", b"")
        if not message.get("more_body", False):
            break
    assert b"tok2" in rest
    assert b"[DONE]" in rest
    await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_non_streaming_json_is_unchanged() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "cmpl-1", "object": "chat.completion"})

    app = _app(handler)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(CHAT_PATH, json={})
    assert resp.status_code == 200
    assert resp.json() == {"id": "cmpl-1", "object": "chat.completion"}


@pytest.mark.asyncio
async def test_upstream_status_and_headers_survive_streaming() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"retry-after": "7", "content-type": "application/json"},
            json={"detail": "slow down"},
        )

    app = _app(handler)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(CHAT_PATH, json={})
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "7"
    assert resp.json()["detail"] == "slow down"


@pytest.mark.asyncio
async def test_compressed_upstream_body_is_decoded() -> None:
    """content-encoding is stripped, so the body must be decoded, not raw."""

    import gzip

    payload = b'{"ok":true}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip", "content-type": "application/json"},
            content=gzip.compress(payload),
        )

    app = _app(handler)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(CHAT_PATH, json={})
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers
    assert resp.content == payload


@pytest.mark.asyncio
async def test_unreachable_upstream_still_maps_to_502() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    app = _app(handler)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(CHAT_PATH, json={})
    assert resp.status_code == 502
    assert resp.json()["service"] == "ai"
