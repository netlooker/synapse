# MCP Requirements

## Purpose

This document defines the minimum runtime contract for exposing Synapse through an MCP server.

The goal is to keep the MCP layer thin:

- Synapse stays the deterministic retrieval and maintenance engine
- the MCP server exposes a small, structured tool surface
- reasoning remains optional and external unless a caller explicitly uses `Cipher`
- the HTTP/OpenAPI adapter can expose the same service layer to web clients without changing core behavior

## Minimum Runtime Requirements

Synapse MCP needs:

- a Python environment with Synapse installed
- `sqlite-vec` installed through the Python package
- a readable markdown folder
- a writable SQLite database path
- one note embedding model endpoint
- one chunk/context embedding model endpoint

The two embedding providers should use matching dimensions for hybrid retrieval.

## Optional Runtime Requirements

Optional, but useful:

- a reasoning model endpoint for `Cipher`
- a local Ollama server for lightweight reasoning
- an Infinity server for `pplx-embed-v1-0.6b` and `pplx-embed-context-v1-0.6b`

If no reasoning model is configured, the core MCP retrieval tools can still work.

## Supported Markdown Inputs

Synapse MCP assumes:

- any folder containing `.md` files
- recursive indexing under the configured root
- include and exclude patterns honored from config
- optional frontmatter, tags, and wikilinks

It does not require Obsidian specifically.

## Current Vector Backend Requirement

Current live backend:

- `sqlite-vec`

Implications:

- no separate database server is required
- the SQLite database file must be writable
- the Python runtime must support SQLite extension loading

## Embedding Requirements

Required for indexing and search:

- note embedding provider
- contextual chunk embedding provider

Recommended default profile:

- `perplexity-ai/pplx-embed-v1-0.6b`
- `perplexity-ai/pplx-embed-context-v1-0.6b`

Current known-good runtimes:

- Infinity
- Ollama for fallback and smaller local experiments

## Configuration Contract

The MCP layer should accept:

- `config_path`
- `vault_root`
- `db_path`
- optional provider overrides where needed

Path argument rule:

- `vault_root` and `db_path` are plain string paths
- callers should send `"/abs/path"` directly, not nested objects
- the MCP layer may normalize obvious local-model wrapper mistakes such as `{ "db_path": { "db_path": "..." } }`
- the MCP layer may also recover common collapsed-string mistakes where safe, for example a `db_path` blob that wrongly contains `vault_root`, `query`, or `mode`

Valid indexing call:

```json
{
  "vault_root": "/data/workspace/e2e/test/ingestion_vault",
  "db_path": "/data/workspace/e2e/test/synapse.sqlite"
}
```

Invalid indexing call:

```json
{
  "db_path": "{\"/data/workspace/e2e/test/synapse.sqlite\"},vault_root:\"/data/workspace/e2e/test/ingestion_vault\""
}
```

Valid search call:

```json
{
  "query": "cross-paper insights about AI and computer science",
  "mode": "hybrid",
  "db_path": "/data/workspace/e2e/test/synapse.sqlite"
}
```

Invalid search call:

```json
{
  "db_path": "{\"/data/workspace/e2e/test/synapse.sqlite\"},mode:\"hybrid\",query:\"cross-paper insights about AI and computer science\""
}
```

Resolution order:

1. explicit MCP tool arguments
2. Synapse config
3. Synapse defaults

## Initial MCP Tool Surface

Core retrieval tools:

- `synapse_health`
- `synapse_health_simple`
- `synapse_index`
- `synapse_index_simple`
- `synapse_search`
- `synapse_search_simple`
- `synapse_discover`
- `synapse_validate`

Cipher tools:

- `synapse_cipher_audit`
- `synapse_cipher_explain`
- `synapse_cipher_chunking_strategy`
- `synapse_cipher_review_stubs`

This keeps MCP aligned with the HTTP/OpenAPI surface while still separating deterministic retrieval from reasoning.

## Health Expectations

`synapse_health` should report:

- effective config path
- effective markdown root
- effective database path
- whether the markdown root exists
- whether the database already exists
- whether `sqlite-vec` is available
- configured note and chunk providers
- whether embedding dimensions match
- whether the environment is ready for indexing

For local-model runtimes, `synapse_health_simple(vault_root, db_path)` is the preferred fast path because it removes optional overrides from the call shape.

## Indexing Expectations

`synapse_index` should:

- scan markdown recursively
- respect include and exclude patterns
- store paths relative to the configured root
- create note and chunk embeddings
- write vectors and metadata to SQLite

For local-model runtimes, `synapse_index_simple(vault_root, db_path)` is the preferred indexing wrapper.

## Search Expectations

`synapse_search` should:

- work against an existing Synapse SQLite index
- support `note`, `chunk`, and `hybrid`
- return structured ranked results

For local-model runtimes, `synapse_search_simple(query, db_path, mode="hybrid")` is the preferred search wrapper.

## Discovery Expectations

`synapse_discover` should:

- return structured hidden-link candidates
- include semantic, metadata, and graph-aware scores

## Validation Expectations

`synapse_validate` should:

- report broken wikilinks from the indexed corpus
- avoid any automatic writes

## Reasoning Boundary

The MCP wrapper should not require a reasoning model for the main retrieval path.

If reasoning is added later:

- keep it in separate `Cipher` tools
- do not make indexing/search/discovery depend on it
- require a configured reasoning model only for the `Cipher` MCP tools, not for the core retrieval tools
- allow timeout defaults from `[cipher]` config and per-call `timeout_seconds` overrides for model-backed `Cipher` operations

## Installation Note

To run the MCP server itself, install the MCP extra:

```bash
.venv/bin/pip install -e ".[dev,mcp]"
```

That provides the Python MCP SDK and CLI support.

If you also want the HTTP/OpenAPI surface in the same environment:

```bash
.venv/bin/pip install -e ".[dev,mcp,api]"
```

## Client Configuration

Synapse should also ship a copy-paste MCP client config, because most agents expect to register a server rather than reconstruct the launch command themselves.

Tracked example:

- [config/synapse.mcp.example.json](../config/synapse.mcp.example.json)

Recommended pattern:

- use the `synapse-mcp` console script
- point `SYNAPSE_CONFIG` at the local `config/synapse.toml`
- keep transport on `stdio`
- `SYNAPSE_CONFIG` is required for `synapse-mcp` startup; do not rely on cwd-relative fallback

Generic `mcpServers` example:

```json
{
  "mcpServers": {
    "synapse": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/ABSOLUTE/PATH/TO/synapse",
        "synapse-mcp"
      ],
      "env": {
        "SYNAPSE_CONFIG": "/ABSOLUTE/PATH/TO/synapse/config/synapse.toml",
        "SYNAPSE_MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

If a client prefers launching the virtualenv executable directly, this also works:

```json
{
  "mcpServers": {
    "synapse": {
      "command": "/ABSOLUTE/PATH/TO/synapse/.venv/bin/synapse-mcp",
      "env": {
        "SYNAPSE_CONFIG": "/ABSOLUTE/PATH/TO/synapse/config/synapse.toml"
      }
    }
  }
}
```

Notes:

- `SYNAPSE_CONFIG` sets the default runtime config for all MCP tools
- tools can still override `config_path`, `vault_root`, or `db_path` per call
- scalar path overrides must be sent as plain strings, not nested objects
- no reasoning-model environment is required for the core retrieval tools
- `Cipher` MCP tools do require reasoning-model configuration, for example `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `SYNAPSE_MODEL`
- when a `Cipher` MCP tool fails, the tool error message carries a structured Synapse error payload with fields such as `error_type`, `retryable`, `dependency`, and `timeout_seconds`
