from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

os.environ["MCP_NAME"] = "ultra-mcp-ss-test"
os.environ["MCP_TRANSPORT"] = "streamable-http"
os.environ["MCP_AUTH_ENABLED"] = "false"
os.environ["MCP_ALLOWED_HOSTS"] = ",".join(
    [
        "localhost",
        "localhost:*",
        "127.0.0.1",
        "127.0.0.1:*",
        "ultra-mcp.u22.ypcloud.com",
    ]
)
os.environ["MCP_ALLOWED_ORIGINS"] = ",".join(
    [
        "http://localhost:*",
        "http://127.0.0.1:*",
        "https://ultra-mcp.u22.ypcloud.com",
    ]
)

from main import app, ss  # noqa: E402


class StreamableHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_context = TestClient(
            app,
            base_url="http://localhost",
            follow_redirects=False,
        )
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)

    @staticmethod
    def rpc_headers(protocol_version: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if protocol_version:
            headers["MCP-Protocol-Version"] = protocol_version
        return headers

    def initialize(self, authorization: str | None = None):
        headers = self.rpc_headers()
        if authorization:
            headers["Authorization"] = authorization
        return self.client.post(
            "/mcp/ss",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "hermes-contract-test",
                        "version": "1.0.0",
                    },
                },
            },
        )

    def test_initialize_and_tools_list_use_exact_public_path(self) -> None:
        initialized = self.initialize()

        self.assertEqual(initialized.status_code, 200, initialized.text)
        self.assertEqual(initialized.headers["content-type"], "application/json")
        body = initialized.json()
        self.assertEqual(body["jsonrpc"], "2.0")
        self.assertEqual(body["id"], 1)
        self.assertEqual(body["result"]["serverInfo"]["name"], "ultra-mcp-ss-test")

        protocol_version = body["result"]["protocolVersion"]
        tools = self.client.post(
            "/mcp/ss",
            headers=self.rpc_headers(protocol_version),
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )

        self.assertEqual(tools.status_code, 200, tools.text)
        names = {tool["name"] for tool in tools.json()["result"]["tools"]}
        self.assertIn("ss_command", names)
        self.assertIn("ss_go", names)
        self.assertIn("ss_notify", names)
        self.assertIn("ss_drop", names)
        self.assertIn("ss_text", names)

    def test_generic_command_tool_uses_same_motebus_client(self) -> None:
        initialized = self.initialize()
        protocol_version = initialized.json()["result"]["protocolVersion"]
        expected = {
            "status": "success",
            "data": {"accepted": True},
            "meta": {"downstream": {"transport": "motebus"}},
        }
        with patch.object(ss, "send", AsyncMock(return_value=expected)) as send:
            response = self.client.post(
                "/mcp/ss",
                headers=self.rpc_headers(protocol_version),
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "ss_command",
                        "arguments": {
                            "ddn": "screen",
                            "data": {"cmd": "page", "option": "show"},
                        },
                    },
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["id"], 3)
        self.assertFalse(body["result"]["isError"])
        send.assert_awaited_once_with(
            {
                "to": {"name": "screen"},
                "data": {"cmd": "page", "option": "show"},
            }
        )

    def test_go_tool_dispatches_qname_as_native_page_command(self) -> None:
        initialized = self.initialize()
        protocol_version = initialized.json()["result"]["protocolVersion"]
        expected = {
            "status": "success",
            "data": {"accepted": True},
            "meta": {"downstream": {"transport": "motebus"}},
        }
        with patch.object(ss, "send", AsyncMock(return_value=expected)) as send:
            response = self.client.post(
                "/mcp/ss",
                headers=self.rpc_headers(protocol_version),
                json={
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "ss_go",
                        "arguments": {
                            "ddn": "kiosk.ss@j22",
                            "route": "101.tv",
                        },
                    },
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["id"], 4)
        self.assertFalse(body["result"]["isError"])
        send.assert_awaited_once_with(
            {
                "to": {"name": "kiosk.ss@j22"},
                "data": {
                    "cmd": "page",
                    "option": "show",
                    "value": {
                        "title": "101.tv",
                        "route": "page://board?type=dock&q=101.tv",
                        "canonicalRoute": "page://board?type=dock&q=101.tv",
                        "frame": "main",
                    },
                },
            }
        )

    def test_native_payload_is_not_accepted_as_mcp_json_rpc(self) -> None:
        response = self.client.post(
            "/mcp/ss",
            headers=self.rpc_headers(),
            json={"to": {"name": "screen"}, "data": {"cmd": "notify"}},
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("payload must contain 'to' and 'data'", response.text)

    def test_native_diagnostic_adapter_moved_to_api_path(self) -> None:
        response = self.client.post("/api/ss", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "payload must contain 'to' and 'data'")

    def test_native_diagnostic_adapter_uses_same_motebus_client(self) -> None:
        expected = {
            "status": "success",
            "data": {"accepted": True},
            "meta": {"downstream": {"transport": "motebus"}},
        }
        with patch.object(ss, "send", AsyncMock(return_value=expected)) as send:
            response = self.client.post(
                "/api/ss",
                json={
                    "to": {"name": "screen"},
                    "data": {"cmd": "notify", "msg": "hello"},
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), expected)
        send.assert_awaited_once()

    def test_unknown_host_is_rejected(self) -> None:
        response = self.client.post(
            "/mcp/ss",
            headers={**self.rpc_headers(), "Host": "untrusted.example"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "host-test", "version": "1.0"},
                },
            },
        )

        self.assertEqual(response.status_code, 421)

    def test_lab_public_host_is_allowed_but_pd_host_is_not(self) -> None:
        lab = self.client.post(
            "/mcp/ss",
            headers={**self.rpc_headers(), "Host": "ultra-mcp.u22.ypcloud.com"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "lab-host-test", "version": "1.0"},
                },
            },
        )
        pd = self.client.post(
            "/mcp/ss",
            headers={**self.rpc_headers(), "Host": "ultra-mcp.ypcloud.com"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pd-host-test", "version": "1.0"},
                },
            },
        )
        pd_alias = self.client.post(
            "/mcp/ss",
            headers={**self.rpc_headers(), "Host": "mcp-ss.ypcloud.com"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pd-alias-test", "version": "1.0"},
                },
            },
        )

        self.assertEqual(lab.status_code, 200, lab.text)
        self.assertEqual(pd.status_code, 421, pd.text)
        self.assertEqual(pd_alias.status_code, 421, pd_alias.text)

    def test_bearer_auth_protects_streamable_http(self) -> None:
        with patch.dict(
            os.environ,
            {"MCP_AUTH_ENABLED": "true", "MCP_AUTH_TOKEN": "contract-token"},
        ):
            unauthorized = self.initialize()
            authorized = self.initialize("Bearer contract-token")

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(authorized.status_code, 200, authorized.text)


if __name__ == "__main__":
    unittest.main()
