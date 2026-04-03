# TODO

## MCP Runtime

### Cache default settings after MCP startup

- Priority: Medium
- Impact: Medium
- Value: Reduces repeated config parsing on every MCP tool call while preserving explicit per-call `config_path` overrides.

Context:
`synapse-mcp` now requires `SYNAPSE_CONFIG` at startup and validates it before serving requests. The current tool path still calls `load_settings()` per request when `config_path` is omitted.

Proposed direction:
- load and validate the default settings once at MCP startup
- reuse that cached settings object for no-override tool calls
- continue resolving settings dynamically when a tool call provides `config_path`
- keep behavior identical for explicit overrides and transport-visible errors

Expected outcome:
- lower per-call overhead for `synapse_health`, `synapse_search`, `synapse_index`, and other MCP tools
- clearer separation between server default config and request-level overrides
- no change to the external MCP contract
