# HTTP API

## Purpose

Synapse now exposes a web-facing JSON API alongside MCP.

Use this interface when:

- a PWA or web UI needs to invoke Synapse
- the client wants OpenAPI schemas
- browser-oriented tooling should call Synapse over normal HTTP

Keep the role split clear:

- MCP is the agent-facing tool interface
- HTTP/OpenAPI is the app-facing interface
- both sit on the same Synapse service layer

## Install

Install the API extra:

```bash
uv sync --extra api
```

Or:

```bash
.venv/bin/pip install -e ".[api]"
```

If you want the full local integration surface in one environment:

```bash
.venv/bin/pip install -e ".[dev,mcp,api]"
```

## Run

Start the local API server:

```bash
uv run synapse-api
```

Default bind:

- host: `127.0.0.1`
- port: `8765`

OpenAPI documents:

- `GET /openapi.json`
- `GET /docs`
- `GET /redoc`
- tracked export: [docs/openapi.json](openapi.json)

## Official Contract

The generated OpenAPI schema is the official app-facing contract for Synapse HTTP integrations.

That means:

- MCP remains the agent-facing contract
- `docs/openapi.json` is the tracked web contract
- the live `/openapi.json` output should match the tracked export for the current revision

Regenerate the tracked file with:

```bash
uv run synapse-export-openapi
```

Or:

```bash
just openapi
```

## Versioning

For now, the HTTP contract follows the repo version and remains `0.x`, which means the API should be treated as evolving but intentional.

Practical rule:

- additive changes are preferred
- route or schema breaking changes should update the tracked `docs/openapi.json` in the same commit
- PWA and web clients should pin to a Synapse release, not just `main`

## Core Routes

Current routes:

- `GET /health`
- `GET /cipher/health`
- `POST /index`
- `POST /search`
- `POST /discover`
- `POST /validate`
- `POST /cipher/audit`
- `POST /cipher/explain`
- `POST /cipher/chunking-strategy`
- `POST /cipher/review-stubs`

Model-backed `Cipher` routes require a reasoning model environment:

- `POST /cipher/explain`
- `POST /cipher/chunking-strategy`
- `POST /cipher/review-stubs`

`POST /cipher/audit` is deterministic and does not require a reasoning backend.

Typical local setup for the model-backed routes:

- `OPENAI_BASE_URL=http://127.0.0.1:11434/v1`
- `OPENAI_API_KEY=ollama`
- `SYNAPSE_MODEL=openai:glm-4.7-flash:latest`

`Cipher` timeout defaults come from `[cipher]` in `config/synapse.toml`, and the model-backed routes above accept per-request `timeout_seconds` overrides that take precedence over those defaults.

## Response Codes

The HTTP API should return transport-useful status codes rather than generic failures.

Current intent:

- `200` for successful synchronous calls
- `400` for bad requests such as invalid modes or incompatible dimensions
- `404` for missing resources such as an absent Synapse database
- `424` when a required dependency is missing, for example an unconfigured reasoning backend
- `504` when a model-backed `Cipher` operation times out
- `503` when an upstream dependency is temporarily unavailable
- `422` for request-shape validation errors from FastAPI/Pydantic

Error bodies use a structured shape:

```json
{
  "detail": {
    "error_type": "timeout",
    "message": "Cipher reasoning timed out after 2.0 seconds.",
    "retryable": true,
    "dependency": "reasoning_model",
    "timeout_seconds": 2.0
  }
}
```

## Example Flow

### Health

```bash
curl "http://127.0.0.1:8765/health?config_path=config/synapse.toml&vault_root=/path/to/notes&db_path=/path/to/synapse.sqlite"
```

### Index

```bash
curl -X POST "http://127.0.0.1:8765/index" \
  -H "content-type: application/json" \
  -d '{
    "config_path": "config/synapse.toml",
    "vault_root": "/path/to/notes",
    "db_path": "/path/to/synapse.sqlite"
  }'
```

### Search

Accepted search modes are `source`, `note`, `evidence`, and `research`.

```bash
curl -X POST "http://127.0.0.1:8765/search" \
  -H "content-type: application/json" \
  -d '{
    "query": "find weak signals across notes",
    "config_path": "config/synapse.toml",
    "db_path": "/path/to/synapse.sqlite",
    "mode": "research",
    "limit": 5
  }'
```

### Cipher Explain

```bash
curl -X POST "http://127.0.0.1:8765/cipher/explain" \
  -H "content-type: application/json" \
  -d '{
    "doc_a": "agency-memory.md",
    "doc_b": "weak-signals.md"
  }'
```

## Design Notes

The HTTP layer should stay thin.

That means:

- request and response models are the contract
- business logic stays in normal Synapse services
- MCP and HTTP should not fork behavior
- `Cipher` remains optional for the core retrieval path

This is the intended long-term integration shape for a web frontend:

- UI calls HTTP/OpenAPI
- agents call MCP
- both reuse the same index, search, discovery, validation, and Cipher services
