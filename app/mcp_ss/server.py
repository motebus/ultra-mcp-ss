"""
Ultra MCP SmartScreen Server — MCP Tool Layer
FastMCP 1.x

- Default transport: Streamable HTTP
- Legacy SSE / STDIO: opt-in (handled by app/main.py or CLI)
- Payload model: SmartScreen-native { to, data }
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Union
import re
from urllib.parse import urlencode

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .motebus import MoteBusSmartScreenClient


# -----------------------------------------------------------------------------
# Environment and MCP initialization
# -----------------------------------------------------------------------------
load_dotenv()


def _provider_path(name: str, default: str) -> str:
    path = os.getenv(name, default).strip()
    if not path.startswith("/") or path == "/" or "/" not in path[1:]:
        raise RuntimeError(f"{name} must be an absolute provider path such as {default}")
    return path.rstrip("/")


def _split_provider_path(path: str) -> tuple[str, str]:
    mount_path, route_name = path.rsplit("/", 1)
    return mount_path or "/", f"/{route_name}"


def _csv_env(name: str, defaults: list[str]) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return defaults
    return [value.strip() for value in raw.split(",") if value.strip()]


MCP_HTTP_PATH = _provider_path("ULTRA_MCP_SS_PATH", "/mcp/ss")
MCP_HTTP_MOUNT_PATH, MCP_HTTP_ROUTE_PATH = _split_provider_path(MCP_HTTP_PATH)
MCP_SSE_PATH = _provider_path("ULTRA_MCP_SS_SSE_PATH", "/sse/ss")
MCP_SSE_MOUNT_PATH, MCP_SSE_ROUTE_PATH = _split_provider_path(MCP_SSE_PATH)
MCP_ALLOWED_HOSTS = _csv_env(
    "MCP_ALLOWED_HOSTS",
    [
        "localhost",
        "localhost:*",
        "127.0.0.1",
        "127.0.0.1:*",
        "[::1]",
        "[::1]:*",
        "ultra-mcp-ss",
        "ultra-mcp-ss:*",
    ],
)
MCP_ALLOWED_ORIGINS = _csv_env(
    "MCP_ALLOWED_ORIGINS",
    [
        "http://localhost:*",
        "http://127.0.0.1:*",
    ],
)

MCP_NAME = os.getenv("MCP_NAME")
if not MCP_NAME:
    raise RuntimeError("MCP_NAME is required")
mcp = FastMCP(
    MCP_NAME,
    instructions="Control SmartScreen targets through the SS provider tools.",
    json_response=True,
    stateless_http=True,
    streamable_http_path=MCP_HTTP_ROUTE_PATH,
    sse_path=MCP_SSE_ROUTE_PATH,
    message_path=f"{MCP_SSE_ROUTE_PATH}/messages/",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=MCP_ALLOWED_HOSTS,
        allowed_origins=MCP_ALLOWED_ORIGINS,
    ),
)

def _normalize_now_time(value: str) -> str:
    """
    Enforce minimum device delay for now+ schedules.
    """
    if value == "now":
        return "now+00:00:01"
    if re.match(r"^now\\+00:00:0{1,2}$", value):
        return "now+00:00:01"
    return value


def _normalize_schcmd(value: Any) -> Any:
    """
    Validate and normalize dj.schcmd payload list.
    - Ensure each item has time or cron
    - Enforce now+ minimum delay
    """
    if not isinstance(value, list):
        return value
    for item in value:
        if not isinstance(item, dict):
            continue
        if "time" in item and isinstance(item.get("time"), str):
            item["time"] = _normalize_now_time(item["time"])
    return value


# -----------------------------------------------------------------------------
# SmartScreen Client (UltraMap-resolved native MoteBus xmsg only)
# -----------------------------------------------------------------------------
ss = MoteBusSmartScreenClient()


# -----------------------------------------------------------------------------
# MCP Tools — SmartScreen (Build Native Payload)
# -----------------------------------------------------------------------------
def _payload(ddn: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "to": {"name": ddn},
        "data": data,
    }


def _ss_go_route(route: str) -> str:
    destination = str(route or "").strip()
    if not destination:
        raise ValueError("route is required")
    if re.match(r"^page://mate(?=$|[/?#])", destination, re.IGNORECASE):
        return re.sub(
            r"^page://mate", "page://remote", destination, flags=re.IGNORECASE
        )
    if re.match(r"^jj://remote(?=$|[/?#])", destination, re.IGNORECASE):
        return re.sub(
            r"^jj://remote", "page://remote", destination, flags=re.IGNORECASE
        )
    if re.match(r"^(?:page|jj)://", destination, re.IGNORECASE):
        return destination
    if re.match(r"^/(?:board|story)/", destination, re.IGNORECASE):
        return destination
    if not re.fullmatch(
        r"[a-z0-9\u3400-\u9fff][a-z0-9\u3400-\u9fff_-]*(?:\.[a-z0-9\u3400-\u9fff][a-z0-9\u3400-\u9fff_-]*)+",
        destination,
        re.IGNORECASE,
    ):
        return destination
    qname = destination.lower()
    mode = (
        "dock"
        if qname.endswith((".me", ".tv", ".ai", ".radio", ".cam"))
        else "board"
    )
    return f"page://board?{urlencode((('type', mode), ('q', qname)))}"


@mcp.tool()
async def ss_command(ddn: str, data: Dict[str, Any]):
    """Send an SS-owned native command through the canonical MoteBus route."""
    return await ss.send(_payload(ddn, data))


@mcp.tool()
async def ss_go(ddn: str, route: str, frame: str = "main"):
    """Run the canonical SS go command for a qname or WebOS page route."""
    resolved_route = _ss_go_route(route)
    return await ss.send(_payload(ddn, {
        "cmd": "page",
        "option": "show",
        "value": {
            "title": route,
            "route": resolved_route,
            "canonicalRoute": resolved_route,
            "frame": frame,
        },
    }))


@mcp.tool()
async def ss_drop(
    ddn: str,
    item: List[str],
    type: str = "url",
    duration: str = "0",
    frame: str = "main",
    animate: str = "fade",
    aniduration: str = "2",
    pmode: str = "loop",
    bgcolor: str = "black",
):
    return await ss.send(_payload(ddn, {
        "cmd": "drop",
        "type": type,
        "src": item,
        "duration": duration,
        "frame": frame,
        "animate": animate,
        "aniduration": aniduration,
        "pmode": pmode,
        "bgcolor": bgcolor,
    }))


@mcp.tool()
async def ss_text(
    ddn: str,
    message: str,
    duration: str = "30",
    color: str = "white",
    size: str = "3",
    bgcolor: str = "black",
    align: str = "center",
    frame: str = "main",
    animate: str = "fade",
    aniduration: str = "2",
):
    return await ss.send(_payload(ddn, {
        "cmd": "text",
        "msg": message,
        "duration": duration,
        "color": color,
        "size": size,
        "bgcolor": bgcolor,
        "align": align,
        "frame": frame,
        "animate": animate,
        "aniduration": aniduration,
    }))


@mcp.tool()
async def ss_marquee(
    ddn: str,
    message: str,
    duration: str = "30",
    color: str = "white",
    size: str = "3",
    bgcolor: str = "black",
):
    return await ss.send(_payload(ddn, {
        "cmd": "marquee",
        "msg": message,
        "duration": duration,
        "color": color,
        "size": size,
        "bgcolor": bgcolor,
    }))


@mcp.tool()
async def ss_notify(ddn: str, message: str, duration: str = "10"):
    return await ss.send(_payload(ddn, {
        "cmd": "notify",
        "msg": message,
        "duration": duration,
    }))


@mcp.tool()
async def ss_toast(
    ddn: str,
    message: str,
    heading: str = "",
    icon: str = "info",
    transition: str = "plain",
    duration: str = "5",
):
    return await ss.send(_payload(ddn, {
        "cmd": "toast",
        "msg": message,
        "heading": heading,
        "icon": icon,
        "transition": transition,
        "duration": duration,
    }))


@mcp.tool()
async def ss_app(
    ddn: str,
    url: str,
    duration: str = "0",
    frame: str = "main",
):
    return await ss.send(_payload(ddn, {
        "cmd": "app",
        "url": url,
        "duration": duration,
        "frame": frame,
    }))


@mcp.tool()
async def ss_home(
    ddn: str,
    duration: str = "0",
    frame: str = "main",
):
    return await ss.send(_payload(ddn, {
        "cmd": "app",
        "url": "https://smartscreen.tv/home",
        "duration": duration,
        "frame": frame,
    }))


@mcp.tool()
async def ss_clear(
    ddn: str,
    frame: str = "main",
):
    return await ss.send(_payload(ddn, {
        "cmd": "drop",
        "type": "url",
        "src": ["about:blank"],
        "duration": "0",
        "frame": frame,
        "bgcolor": "black",
    }))


@mcp.tool()
async def ss_default(
    ddn: str,
):
    return await ss.send(_payload(ddn, {
        "cmd": "dj",
        "option": "defcmd",
    }))


@mcp.tool()
async def ss_clear_schedule(
    ddn: str,
):
    return await ss.send(_payload(ddn, {
        "cmd": "dj",
        "option": "schcmd",
        "value": [],
    }))


@mcp.tool()
async def ss_html(
    ddn: str,
    html: str,
    duration: str = "0",
    frame: str = "main",
):
    return await ss.send(_payload(ddn, {
        "cmd": "html",
        "contain": html,
        "duration": duration,
        "frame": frame,
    }))


@mcp.tool()
async def ss_frame(ddn: str, layout: str):
    return await ss.send(_payload(ddn, {
        "cmd": "frame",
        "layout": layout,
    }))


@mcp.tool()
async def ss_touch(ddn: str, option: str, value: str = ""):
    return await ss.send(_payload(ddn, {
        "cmd": "touch",
        "option": option,
        "value": value,
    }))


@mcp.tool()
async def ss_status(ddn: str, option: str, value: str = ""):
    return await ss.send(_payload(ddn, {
        "cmd": "status",
        "option": option,
        "value": value,
    }))


@mcp.tool()
async def ss_dj(
    ddn: str,
    option: str,
    value: Union[str, List[Dict[str, Any]], Dict[str, bool]] = "",
):
    if option == "schcmd":
        value = _normalize_schcmd(value)
    return await ss.send(_payload(ddn, {
        "cmd": "dj",
        "option": option,
        "value": value,
    }))


@mcp.tool()
async def ss_help():
    return {
        "display_tools": [
            "ss_go",
            "ss_drop",
            "ss_text",
            "ss_marquee",
            "ss_notify",
            "ss_toast",
            "ss_app",
            "ss_html",
            "ss_home",
            "ss_clear",
        ],
        "layout_tools": [
            "ss_frame",
        ],
        "control_tools": [
            "ss_command",
            "ss_touch",
            "ss_status",
            "ss_dj",
            "ss_default",
            "ss_clear_schedule",
        ],
    }
