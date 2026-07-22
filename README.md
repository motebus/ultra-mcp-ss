# ultra-mcp-ss (lab)

SmartScreen MCP adapter for external MCP clients.

Lab placement: `u22`, exposed as
`https://ultra-mcp.u22.ypcloud.com/mcp/ss`.

## Endpoints

- `POST /mcp/ss`: standard MCP Streamable HTTP JSON-RPC endpoint.
- `GET /mcp/ss`: optional Streamable HTTP server event stream.
- `GET /sse/ss`: legacy MCP SSE transport when `MCP_TRANSPORT=http+sse`.
- `POST /api/ss`: native `{to,data}` HTTP ingress for diagnostics; downstream
  delivery still uses MoteBus only.
- `GET /ping`: process health.

Every SmartScreen operation uses this downstream route:

- Read `ultra_ss_app_lab_mma` from `u22/comm/comm-app` on
  `map://ultra-map-dev`.
- Validate the selected `ultra-map` source and resolved
  `u22/ss/ss-srv-app` owner.
- Send the native `{to,data}` screen command through MoteBus xmsg on
  `ss://mms`. Do not add reserved transport markers to the command body.
- Fail visibly if map resolution, MoteChat, the owner, or its reply is
  unavailable. There is no HTTP or alternate-transport fallback.

An MCP client must initialize the session before listing or calling tools. For
Hermes, register the public MCP URL, reload MCP discovery, and expect tools
such as `ss_notify`, `ss_drop`, `ss_go`, and `ss_text`. `ss_go` is the
first-class MCP form of `/ss go <qname-or-page-route>`; for example, `101.tv`
dispatches the native WebOS route `page://board?type=dock&q=101.tv`. The
constrained `ss_command` tool lets the canonical SS skill carry SS-owned native
command data through a standard MCP `tools/call` request; it does not change
the MoteBus-only downstream route.

DNS-rebinding protection remains enabled. The Lab Compose configuration allows
only the Lab public hostname plus local/container names. PD independently
allows `mcp-ss.ypcloud.com` and the shared `ultra-mcp.ypcloud.com` gateway; PD
and Lab aliases are not interchangeable.

MoteChat startup identity and gateway settings are held only in the locked
`ultra-mcp-ss-mchat.env` topology contract. The selected UltraMap tier is
declared separately by Compose through `ULTRA_MCP_SS_MAP_TIER`.
