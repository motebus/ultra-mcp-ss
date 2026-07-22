"""Native MoteBus subprocess adapter for SmartScreen dispatch."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping


RESULT_PREFIX = "@@ULTRA_MCP_SS_RESULT@@"
REQUIRED_MCHAT_ENV = (
    "MCHAT_APPNAME",
    "MCHAT_DC",
    "MCHAT_IOC",
    "MCHAT_MBGWIP",
    "MCHAT_WATCHLEVEL",
)
CHILD_ENV_KEYS = (
    *REQUIRED_MCHAT_ENV,
    "MCHAT_EINAME",
    "ULTRA_MCP_SS_MAP_TIER",
    "ULTRA_MCP_SS_SEND_TIMEOUT",
    "ULTRA_MCP_SS_WAIT_REPLY",
    "NODE_PATH",
    "PATH",
    "HOME",
    "TZ",
)


def motebus_config_status(env: Mapping[str, str] | None = None) -> Dict[str, Any]:
    source = os.environ if env is None else env
    missing = [name for name in REQUIRED_MCHAT_ENV if not source.get(name, "").strip()]
    tier = source.get("ULTRA_MCP_SS_MAP_TIER", "").strip()
    if not tier:
        missing.append("ULTRA_MCP_SS_MAP_TIER")
    return {
        "configured": not missing,
        "missing": missing,
        "map_tier": tier or None,
        "transport": "motebus",
        "command": "xmsg",
        "topic": "ss://mms",
        "fallback": "none",
    }


def _child_environment(env: Mapping[str, str]) -> Dict[str, str]:
    child = {name: env[name] for name in CHILD_ENV_KEYS if env.get(name)}
    child.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    child.setdefault("NODE_PATH", "/opt/motebus/node_modules")
    return child


def _parse_result(stdout: bytes) -> Dict[str, Any] | None:
    text = stdout.decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        if not line.startswith(RESULT_PREFIX):
            continue
        try:
            value = json.loads(line[len(RESULT_PREFIX):])
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None
    return None


def _error(code: str, detail: str, meta: Dict[str, Any] | None = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "status": "error",
        "error_code": code,
        "detail": detail,
    }
    if meta:
        result["meta"] = meta
    return result


class MoteBusSmartScreenClient:
    """Dispatch SmartScreen envelopes through the bundled native xmsg bridge."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env = env
        self._bridge = Path(__file__).with_name("motebus_dispatch.mjs")

    @property
    def env(self) -> Mapping[str, str]:
        return os.environ if self._env is None else self._env

    async def send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        status = motebus_config_status(self.env)
        if not status["configured"]:
            return _error(
                "motebus_config_missing",
                f"Missing runtime configuration: {', '.join(status['missing'])}",
                {"downstream": status},
            )

        try:
            process_timeout = float(
                self.env.get("ULTRA_MCP_SS_PROCESS_TIMEOUT_SECONDS", "90")
            )
        except ValueError:
            return _error(
                "motebus_config_invalid",
                "ULTRA_MCP_SS_PROCESS_TIMEOUT_SECONDS must be numeric",
                {"downstream": status},
            )
        if process_timeout <= 0:
            return _error(
                "motebus_config_invalid",
                "ULTRA_MCP_SS_PROCESS_TIMEOUT_SECONDS must be positive",
                {"downstream": status},
            )

        try:
            process = await asyncio.create_subprocess_exec(
                "/usr/local/bin/node",
                str(self._bridge),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_child_environment(self.env),
            )
        except OSError as exc:
            return _error(
                "motebus_runtime_unavailable",
                f"Native MoteBus bridge could not start: {exc}",
                {"downstream": status},
            )

        request = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(request),
                timeout=process_timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return _error(
                "motebus_timeout",
                f"Native MoteBus dispatch exceeded {process_timeout:g} seconds",
                {"downstream": status},
            )
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise

        bridge_result = _parse_result(stdout)
        if bridge_result is None:
            return _error(
                "motebus_invalid_reply",
                "Native MoteBus bridge did not return a valid result envelope",
                {"downstream": status, "exit_code": process.returncode},
            )

        meta = bridge_result.get("meta")
        if bridge_result.get("ok") is not True or process.returncode != 0:
            error = bridge_result.get("error")
            error = error if isinstance(error, dict) else {}
            return _error(
                str(error.get("code") or "motebus_dispatch_failed"),
                str(error.get("detail") or "Native MoteBus dispatch failed"),
                meta if isinstance(meta, dict) else {"downstream": status},
            )

        return {
            "status": "success",
            "data": bridge_result.get("result"),
            "meta": meta or {"downstream": status},
        }


__all__ = [
    "MoteBusSmartScreenClient",
    "RESULT_PREFIX",
    "motebus_config_status",
]
