# ADR-008: a tool registry and an MCP gateway in front of every tool call (design only)

**Status:** proposed, 2026-11-17 (week 5). A design write-up: **nothing here was built.** No registry, gateway, MCP
server or auth code exists in the repo; the tools still run in process (`tools.run_tool`).

**Context.** Week 4 gave the analysis three tools, `get_indicators`, `get_levels` and `get_fundamentals`
(`tools.TOOLS`). They are read-only views of rows the Context already holds, run in the same Python process as the
tool loop (`analyze.analyze_with_tools`), with no caller identity, no permission check and no rate limit: whoever runs
`tr` may call any of them as often as the loop allows (`MAX_TOOL_TURNS` = 5 model calls per item). What is already
recorded: each tool call is a `ToolSpan` in the run's trace (`data/traces/<run_id>.jsonl`: tool name, arguments,
result, error, parent model span), and each model call's provider route is kept in the trace (`provider_route`) and
on the stored analysis (`provider_route`, `openrouter:mixed(...)` when the turns of one loop were served by different
hosts, ADR-005). The question for later weeks (more tools, tools that write, a second caller such as a scheduled job
or another team's agent): where do "who may call which tool, how often, and what did they call" live?

The MCP specification already places some of this on the server: a server **MUST** validate tool inputs, implement
access controls, rate limit tool invocations and sanitise outputs, and a client **SHOULD** log tool usage for audit
(Tools, "Security Considerations"). `tools/list` **MAY** return only the tools the caller's granted scopes permit
(Tools, "Capabilities"). A tool definition carries `name`, `description`, `inputSchema` and optional `outputSchema`
and `annotations`, which clients **MUST** treat as untrusted unless the server is trusted (Tools, "Tool"); it has no
version or owner field. Over HTTP, authorization is OAuth 2.1 with the MCP server as resource server: it **MUST**
validate that a token was issued for it (audience, RFC 8707 resource indicators) and **MUST NOT** pass a client's token
on to another service; a missing scope is `403` with `error="insufficient_scope"` (Authorization). Over stdio the spec
says not to use this flow and to take credentials from the environment. The public MCP Registry lists *servers*
(`server.json`, reverse-DNS names verified by GitHub or DNS, immutable versions) and does not take private servers; it
recommends a private registry for those (MCP Registry docs).

**Options considered.**
1. **Keep in-process tools, add checks in `tools.py`.** A scope table in code and an audit line per call. Cheapest,
   but every new caller re-implements the checks, and nothing stops a caller that imports `run_tool` directly.
2. **One MCP server per tool owner, each doing its own auth, limits and logs.** What the MCP spec asks of a server,
   repeated per server; scopes, limit values and log formats drift between servers, and a caller needs one token per
   server.
3. **A tool registry plus one gateway (chosen).** The registry is the list of tool definitions; the gateway is the
   single entry point (the API gateway pattern) that every call passes: it authenticates the caller, authorises the
   tool and scope from the registry, rate-limits, and writes one audit record per call before forwarding to the
   owning MCP server.

**Decision.** Option 3, as a design for when a second caller or a writing tool appears; until then the tools stay in
process (ADR-005 kept the fixed context, so the tools run only as an experiment arm).
- **Registry.** One entry per tool: `name` (unique across servers, prefixed by owner as the spec suggests for
  aggregators, e.g. `tr.get_indicators`), `inputSchema` and `outputSchema` (JSON Schema, as MCP), `version` (a new
  schema is a new version; old versions stay readable, like the registry's immutable versions), `owner` (the team
  that answers for it), `scopes` (e.g. `journal:read`), `side_effects` (`read` or `write`) and the limit. The first
  three entries are the week-4 tools, all `journal:read`, `read`: `get_indicators`, `get_levels`,
  `get_fundamentals`. The registry is private (the public MCP Registry does not hold private servers).
- **Gateway, per call.** (a) Authenticate: an OAuth 2.1 bearer token whose audience is the gateway; the gateway gets
  its own token for the upstream server instead of passing the caller's on. (b) Authorise: the token's scopes must
  cover the tool's scopes, else `403 insufficient_scope`; `tools/list` returns only the permitted tools. (c) Validate
  the arguments against the registered `inputSchema`. (d) Rate-limit per caller and tool, answering `429 Too Many
  Requests`. (e) Audit: one append-only record per call (caller, tool, version, arguments digest, decision, result
  status, latency, the calling run's `run_id` and span id), kept with the trace so a run's tool calls and its audit
  records join on span id.
- **Route and provenance stay where they are.** The model call's route (`provider_route`) stays in the trace and on
  the analysis; the gateway adds which server and tool version served each tool call, so an analysis can be traced
  from model route through tool calls to the rows they returned.

**What changes versus in-process tools.**
- A tool call becomes a network call: latency and a failure mode (gateway down, `401`, `403`, `429`) that
  `run_tool` never had; the loop must turn them into `{"error": ...}` results the model can read, as `ToolError` does.
- The `ToolSpan` stays the record of what the model asked and got; the audit record adds who asked and whether it was
  allowed, which the trace cannot say today because there is one caller.
- Tool schemas move from `tools.TOOLS` to the registry; `ToolCallsOk` (`max_calls`) and the prompt's tool list would
  read the registered set, and a schema change needs a version bump.
- Credentials: a token per caller instead of none; stdio servers would take theirs from the environment.

**Consequences.**
- One more service to run and keep up; for three read-only tools on one machine that is pure cost today, hence
  "design only" until a second caller or a writing tool exists.
- Tool access is decided in one place, and every call leaves an audit record, which a writing tool (orders,
  journal edits) would require before it is allowed at all.
- Experiments over tools must pin the registry version of each tool, as they pin the prompt and model, or two arms
  could call different tool versions.

**Gaps.**
- Nothing measured: no latency, cost or failure numbers for a gateway, because none exists.
- The token issuer, key storage and how a scheduled `tr daily` gets a token are not designed.
- Limit values are not chosen. The only usage numbers on hand are ADR-005's tools arm: 3.05 tool calls per item on
  average over 20 items, 4 at most (AAPL:2026-11-12), none at the 5-model-call limit.

**Readings.**
- MCP specification 2026-07-28, Tools (definition fields, `tools/list` by scope, Security Considerations):
  https://modelcontextprotocol.io/specification/2026-07-28/server/tools
- MCP specification 2026-07-28, Authorization (OAuth 2.1 resource server, audience, `insufficient_scope`, stdio):
  https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization and its security considerations
  (token passthrough forbidden, confused deputy):
  https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations
- MCP Registry (server metadata, namespaces, immutable versions, no private servers):
  https://modelcontextprotocol.io/registry
- API gateway pattern (a single entry point routing requests to services): https://microservices.io/patterns/apigateway.html
- OAuth scopes: RFC 6749 §3.3 https://www.rfc-editor.org/rfc/rfc6749.html; `insufficient_scope`: RFC 6750 §3.1
  https://www.rfc-editor.org/rfc/rfc6750.html; resource indicators (token audience): RFC 8707
  https://www.rfc-editor.org/rfc/rfc8707.html
- Rate limiting, `429 Too Many Requests`: RFC 6585 §4 https://www.rfc-editor.org/rfc/rfc6585.html
- Audit logs: NIST SP 800-92, Guide to Computer Security Log Management https://csrc.nist.gov/pubs/sp/800/92/final
