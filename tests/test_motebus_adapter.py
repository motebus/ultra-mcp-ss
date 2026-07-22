from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from mcp_ss.motebus import (  # noqa: E402
    MoteBusSmartScreenClient,
    RESULT_PREFIX,
    _parse_result,
    motebus_config_status,
)


def valid_env() -> dict[str, str]:
    return {
        "MCHAT_APPNAME": "mcp-ss",
        "MCHAT_EINAME": "mcp-ss",
        "MCHAT_DC": "dc",
        "MCHAT_IOC": "ioc",
        "MCHAT_MBGWIP": "motebus:6262",
        "MCHAT_WATCHLEVEL": "1",
        "ULTRA_MCP_SS_MAP_TIER": "dev",
        "MCP_AUTH_TOKEN": "must-not-reach-child",
    }


class FakeProcess:
    def __init__(self, result: dict, returncode: int = 0) -> None:
        self.returncode = returncode
        self.result = result
        self.request = b""
        self.killed = False

    async def communicate(self, request: bytes):
        self.request = request
        stdout = f"sdk log\n{RESULT_PREFIX}{__import__('json').dumps(self.result)}\n"
        return stdout.encode(), b"ignored sdk stderr"

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


class MoteBusAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_config_status_does_not_expose_topology_values(self) -> None:
        status = motebus_config_status(valid_env())

        self.assertTrue(status["configured"])
        self.assertEqual(status["map_tier"], "dev")
        self.assertNotIn("MCHAT_MBGWIP", status)

    def test_result_parser_ignores_sdk_logs(self) -> None:
        parsed = _parse_result(
            f"registration log\n{RESULT_PREFIX}{'{\"ok\":true}'}\n".encode()
        )

        self.assertEqual(parsed, {"ok": True})

    async def test_send_returns_structured_result_and_filters_child_env(self) -> None:
        process = FakeProcess(
            {
                "ok": True,
                "result": {"accepted": True},
                "meta": {"downstream": {"transport": "motebus", "topic": "ss://mms"}},
            }
        )
        spawn = AsyncMock(return_value=process)
        client = MoteBusSmartScreenClient(valid_env())

        with patch("mcp_ss.motebus.asyncio.create_subprocess_exec", spawn):
            result = await client.send(
                {"to": {"name": "screen"}, "data": {"cmd": "notify"}}
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"], {"accepted": True})
        child_env = spawn.await_args.kwargs["env"]
        self.assertNotIn("MCP_AUTH_TOKEN", child_env)
        self.assertEqual(child_env["MCHAT_APPNAME"], "mcp-ss")

    async def test_missing_mchat_config_fails_before_process_start(self) -> None:
        client = MoteBusSmartScreenClient({"ULTRA_MCP_SS_MAP_TIER": "P"})
        spawn = AsyncMock()

        with patch("mcp_ss.motebus.asyncio.create_subprocess_exec", spawn):
            result = await client.send(
                {"to": {"name": "screen"}, "data": {"cmd": "notify"}}
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "motebus_config_missing")
        spawn.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
