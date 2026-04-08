# Agent Introduction

This document is the shortest complete briefing for an external coding or operations agent that needs to work on Synapse.

Repository:

- GitHub: [netlooker/synapse](https://github.com/netlooker/synapse)
- If the agent has GitHub CLI access, it can access the repository via `gh`, for example:

```bash
gh repo clone netlooker/synapse
```

## What Synapse Is

Synapse is a semantic retrieval and discovery engine for markdown knowledge bases.

Its job is to:

- index any folder of markdown files recursively
- split notes into meaningful chunks
- embed both notes and chunks
- store vectors and metadata in a local vector-capable database
- perform semantic search
- surface hidden relationships across notes
- support a reasoning layer called `Cipher` for audit, explanation, and maintenance review

Synapse is not a notes app and not a chatbot shell. It is the memory and retrieval substrate that other agents or applications can call.

## Current Architecture

Synapse has three main layers.

### 1. Deterministic retrieval core

Normal Python services handle:

- file discovery
- markdown parsing
- frontmatter, tags, and wikilinks
- chunking
- embeddings
- vector storage
- search
- discovery
- validation

Important modules:

- [synapse/index.py](../synapse/index.py)
- [synapse/search.py](../synapse/search.py)
- [synapse/discovery.py](../synapse/discovery.py)
- [synapse/validate.py](../synapse/validate.py)
- [synapse/db.py](../synapse/db.py)
- [synapse/vector_store.py](../synapse/vector_store.py)

### 2. Reasoning layer

`Cipher` is the reasoning shell over the retrieval core.

It handles tasks like:

- auditing a vault
- explaining why two notes are connected
- suggesting chunking strategy
- reviewing stub-note proposals

Important module:

- [synapse/cipher_service.py](../synapse/cipher_service.py)

### 3. Transport layer

Synapse exposes the same capabilities over:

- MCP for agents
- HTTP/OpenAPI for web or app integrations

Important modules:

- [synapse/mcp_server.py](../synapse/mcp_server.py)
- [synapse/web_api.py](../synapse/web_api.py)
- [synapse/service_api.py](../synapse/service_api.py)

## What Synapse Expects

At minimum, Synapse needs:

- Python `3.12+`
- a folder containing markdown files
- a writable SQLite database path
- `sqlite-vec` available through the Python package install
- at least one embedding model provider

Recommended:

- a note embedding model
- a contextual chunk embedding model
- a separate reasoning model for `Cipher`

Optional markdown features that improve results:

- YAML frontmatter
- tags
- wikilinks such as `[[Some Note]]`

## Known Good Runtime Shape

The tracked example config is currently optimized for:

- note embeddings from `perplexity-ai/pplx-embed-v1-0.6b`
- contextual chunk embeddings from `perplexity-ai/pplx-embed-context-v1-0.6b`
- providers served by Infinity or Ollama
- local vector storage via `sqlite-vec`

The tracked example config is:

- [config/synapse.example.toml](../config/synapse.example.toml)

The tracked MCP client example is:

- [config/synapse.mcp.example.json](../config/synapse.mcp.example.json)

## Installation

Standard setup:

```bash
uv sync
```

Contributor or test setup:

```bash
uv sync --extra dev --extra api --extra mcp
```

Or with `pip`:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,api,mcp]"
```

Notes:

- `sqlite-vec` is installed as a normal dependency
- `dev` now includes the test-time API and MCP dependencies required by the current suite
- no separate bundled SQLite extension file is required

## Configuration

Create a local config:

```bash
cp config/synapse.example.toml config/synapse.toml
```

Then set:

- `[vault].root`
- `[database].path`
- `[providers.embeddings.*]` endpoints and model names
- `[cipher]` timeouts if needed

Override order:

1. CLI arguments
2. environment variables
3. `config/synapse.toml`
4. built-in defaults

## Primary Entry Points

CLI:

- `synapse-smoke`
- `synapse-index`
- `synapse-search`
- `synapse-discover`
- `synapse-validate`
- `synapse-garden`
- `synapse-mcp`
- `synapse-api`
- `synapse-export-openapi`

Python service entry points:

- [synapse/service_api.py](../synapse/service_api.py)
- [synapse/cipher_service.py](../synapse/cipher_service.py)

## Typical Agent Workflow

For an agent coming into the project cold, use this order:

1. Clone or open the repo with `gh` access.
2. Read [README.md](../README.md).
3. Read [docs/openclaw-integration.md](openclaw-integration.md).
4. Copy the example config and set the vault root, DB path, and embedding endpoints.
5. Run `synapse-smoke` first to verify providers, indexing, retrieval, and dry-run maintenance against the bundled fixture vault.
6. Run indexing on a markdown folder.
7. Run search and discovery.
8. Use `Cipher` only when reasoning or maintenance review is needed.
9. Use MCP if the agent runtime is tool-based; use HTTP if integrating with a web app or PWA.

## Smoke Test

Before touching a real vault, run the bundled dry-run command:

```bash
uv run synapse-smoke --config config/synapse.toml
```

What it does:

- uses the bundled fixture vault by default
- creates a fresh temporary SQLite DB by default
- runs health, index, search, discovery, validation, and gardener dry-run
- optionally runs one model-backed `Cipher` explanation step when the reasoning env is configured

Important behavior:

- the smoke command refuses to reuse an existing DB path unless `--reuse-db` is passed
- this avoids stale entries when a DB has been reused across different vault roots

## Minimal Commands

Smoke:

```bash
uv run synapse-smoke --config config/synapse.toml
```

Index:

```bash
uv run synapse-index \
  --config config/synapse.toml \
  --vault-root /path/to/markdown \
  --db /path/to/synapse.sqlite
```

Search:

```bash
uv run synapse-search \
  --config config/synapse.toml \
  --db /path/to/synapse.sqlite \
  --mode hybrid \
  "find weak signals across notes"
```

Discover:

```bash
uv run synapse-discover \
  --config config/synapse.toml \
  --db /path/to/synapse.sqlite \
  --threshold 0.20 \
  --top-k 3 \
  --max 20
```

Run MCP:

```bash
uv run synapse-mcp
```

Run HTTP API:

```bash
uv run synapse-api
```

Export OpenAPI:

```bash
uv run synapse-export-openapi
```

## Reasoning Model Notes

Core retrieval does not require a reasoning model.

`Cipher` operations such as explanation and chunking advice do.

Typical local env:

```bash
export OPENAI_BASE_URL=http://127.0.0.1:11434/v1
export OPENAI_API_KEY=ollama
export SYNAPSE_MODEL=openai:glm-4.7-flash:latest
```

Timeouts are configurable in `[cipher]` and can also be overridden per request for MCP and HTTP calls.

## Error Semantics

HTTP uses explicit status codes for common failure modes, including:

- `400` bad request
- `404` missing resource
- `424` dependency unavailable
- `503` upstream unavailable
- `504` timeout

MCP mirrors the same semantics through structured error payloads.

## Related Docs

- [README.md](../README.md)
- [docs/architecture.md](architecture.md)
- [docs/openclaw-integration.md](openclaw-integration.md)
- [docs/http-api.md](http-api.md)
- [docs/mcp-requirements.md](mcp-requirements.md)
- [docs/cipher-interface.md](cipher-interface.md)
- [docs/openapi.json](openapi.json)

## Important Current Truths

- The project accepts any markdown folder, including nested subfolders.
- `sqlite-vec` is the live vector backend today.
- The vector backend is behind a seam, so another backend can be added later.
- MCP and HTTP are intentionally aligned over the same service layer.
- `Cipher` is a reasoning shell around deterministic services, not the place where core retrieval logic should live.

## What An Agent Should Not Assume

- Do not assume Obsidian-specific behavior is required.
- Do not assume only one embedding provider exists.
- Do not assume `Cipher` is required for indexing or search.
- Do not assume HTTP is the only integration path.
- Do not assume local machine-specific config belongs in tracked files.
