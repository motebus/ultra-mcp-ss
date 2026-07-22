"""
Ultra MCP SmartScreen Server
FastMCP 1.x

- Default: MCP Streamable HTTP at /mcp/ss
- Optional: legacy MCP SSE at /sse/ss
- Native SmartScreen diagnostic endpoint: /api/ss
"""

from __future__ import annotations

import os
import logging
import secrets
from typing import Any, Dict, Iterable, List, Tuple

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from mcp_ss.server import (
    MCP_HTTP_MOUNT_PATH,
    MCP_HTTP_PATH,
    MCP_SSE_MOUNT_PATH,
    MCP_SSE_PATH,
    mcp,
    ss,
)
from mcp_ss.motebus import motebus_config_status
from mcp_ss import server as _  # register MCP tools on import


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | ultra-mcp-ss | %(levelname)s | %(message)s",
)
log = logging.getLogger("ultra-mcp-ss")


def _normalize_mcp_headers(
    scope: dict,
    extra_drop_headers: Iterable[bytes] = (),
) -> dict:
    drop_headers = {
        b"forwarded",
        b"x-forwarded-host",
    }
    drop_headers.update(extra_drop_headers)

    host_header = os.getenv("MCP_SSE_HOST", "").strip()
    if not host_header:
        raw_host = dict(scope.get("headers", [])).get(b"host", b"")
        host_header = raw_host.decode("latin-1") if raw_host else ""

    headers: List[Tuple[bytes, bytes]] = []
    for name, value in scope.get("headers", []):
        if name.lower() in drop_headers or name.lower() == b"host":
            continue
        headers.append((name, value))

    if host_header:
        headers.append((b"host", host_header.encode("latin-1")))

    normalized = dict(scope)
    normalized["headers"] = headers
    return normalized


def wrap_mcp_app(mcp_app):
    async def asgi(scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            scope = _normalize_mcp_headers(scope)
        await mcp_app(scope, receive, send)

    return asgi


def resolve_transport() -> str:
    raw = (
        os.getenv("MCP_TRANSPORT")
        or os.getenv("MCP_MODE")
        or "streamable-http"
    ).strip().lower()

    aliases = {
        "http": "streamable-http",
        "streamable-http": "streamable-http",
        "streamable_http": "streamable-http",
        "native": "native-api",
        "native-api": "native-api",
        "api": "native-api",
        "sse": "streamable-http+sse",
        "http+sse": "streamable-http+sse",
        "streamable-http+sse": "streamable-http+sse",
        "stdio": "stdio",
        "studio": "stdio",
    }
    return aliases.get(raw, "streamable-http")


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def token_protection_enabled() -> bool:
    if os.getenv("MCP_AUTH_ENABLED") is not None:
        return env_flag("MCP_AUTH_ENABLED", False)
    return env_flag("MCP_TOKEN_PROTECTION_ENABLED", False)


def expected_token() -> str:
    return (
        os.getenv("MCP_AUTH_TOKEN")
        or os.getenv("MCP_TOKEN_PROTECTION_TOKEN")
        or ""
    ).strip()


def path_requires_token(path: str) -> bool:
    protected_paths = (MCP_HTTP_PATH, MCP_SSE_PATH, "/api/ss")
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in protected_paths)


def request_token(request: Request) -> str:
    auth = request.headers.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-mcp-token", "").strip()


# -----------------------------------------------------------------------------
# FastAPI App (AUTHORITATIVE HTTP LAYER)
# -----------------------------------------------------------------------------
mcp_http_app = mcp.streamable_http_app()

app = FastAPI(
    title="Ultra MCP SmartScreen Server",
    version="3.0.1",
    description="SmartScreen MCP adapter with Streamable HTTP ingress",
    lifespan=mcp_http_app.router.lifespan_context,
)


@app.middleware("http")
async def protect_remote_mcp(request: Request, call_next):
    if not token_protection_enabled() or not path_requires_token(request.url.path):
        return await call_next(request)

    token = expected_token()
    if not token:
        log.error("MCP auth is enabled but MCP_AUTH_TOKEN is empty")
        return JSONResponse(
            status_code=503,
            content={"detail": "MCP auth is enabled but token is not configured"},
        )

    supplied = request_token(request)
    if not supplied or not secrets.compare_digest(supplied, token):
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)


# -----------------------------------------------------------------------------
# Health & Debug
# -----------------------------------------------------------------------------
@app.get("/ping")
async def ping():
    return {
        "status": "ok",
        "service": "ultra-mcp-ss",
        "transport": resolve_transport(),
        "token_protection_enabled": token_protection_enabled(),
        "downstream": motebus_config_status(),
    }


@app.get("/test")
async def test():
    tools = await mcp.list_tools()
    return {
        "status": "ok",
        "tools": [tool.name for tool in tools],
    }


# -----------------------------------------------------------------------------
# Native HTTP SmartScreen Endpoint (DIAGNOSTIC ADAPTER)
# -----------------------------------------------------------------------------
@app.post("/api/ss")
async def http_smartscreen_exec(payload: Dict[str, Any]):
    """
    SmartScreen-native HTTP ingress with MoteBus-only downstream dispatch.

    Expected payload:
    {
      "to": { "name": "<device-name>" },
      "data": { ... SmartScreen native command ... }
    }
    """

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if "to" not in payload or "data" not in payload:
        raise HTTPException(
            status_code=400,
            detail="payload must contain 'to' and 'data'",
        )

    if not isinstance(payload["to"], dict) or "name" not in payload["to"]:
        raise HTTPException(
            status_code=400,
            detail="payload.to.name is required",
        )

    if not isinstance(payload["data"], dict) or "cmd" not in payload["data"]:
        raise HTTPException(
            status_code=400,
            detail="payload.data.cmd is required",
        )

    # Forward the native payload through UltraMap-resolved MoteBus xmsg.
    return await ss.send(payload)


# -----------------------------------------------------------------------------
# MCP transports
# -----------------------------------------------------------------------------
transport = resolve_transport()

if transport in {"streamable-http", "streamable-http+sse"}:
    app.mount(MCP_HTTP_MOUNT_PATH, wrap_mcp_app(mcp_http_app))
    log.info("MCP Streamable HTTP endpoint: %s", MCP_HTTP_PATH)
    if transport == "streamable-http+sse":
        app.mount(
            MCP_SSE_MOUNT_PATH,
            wrap_mcp_app(mcp.sse_app(MCP_SSE_MOUNT_PATH)),
        )
        log.info("MCP legacy SSE endpoint: %s", MCP_SSE_PATH)
elif transport == "native-api":
    log.info("MCP mode: native-api only")
elif transport == "stdio":
    log.info("MCP mode: stdio")
else:
    log.info("MCP mode: native-api only")


if __name__ == "__main__":
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        import uvicorn

        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=int(os.getenv("PORT", "8000")),
            reload=False,
            access_log=True,
            log_level="info",
        )
