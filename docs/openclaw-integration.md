# OpenClaw Integration

## Purpose

This document is the practical integration guide for external agents such as OpenClaw.

For the shortest complete project briefing before using this guide, start with [docs/agent-introduction.md](agent-introduction.md).

Use it when an agent needs to:

- install Synapse
- point Synapse at a markdown folder
- build or refresh an index
- run semantic search
- run hidden-link discovery
- call `Cipher` for audit or explanation tasks

The core contract is simple:

- input: any markdown folder
- storage: a Synapse SQLite database
- retrieval: deterministic CLI or Python services
- reasoning: `Cipher` on top of those services
- transport: MCP for agents, HTTP/OpenAPI for app UIs

## What Synapse Expects

Synapse does not require Obsidian or any other notes product.

It expects:

- a folder containing `.md` files
- a writable path for the vector index database
- at least one embedding provider configured

Optional metadata that improves results:

- frontmatter
- tags
- wikilinks like `[[Some Note]]`

If OpenClaw wants to register Synapse as an MCP server instead of shelling out to CLI commands, use the tracked client example at [config/synapse.mcp.example.json](../config/synapse.mcp.example.json) and adjust the absolute paths for the current machine.

If a web UI needs to invoke the same functionality over HTTP, use the OpenAPI interface documented in [docs/http-api.md](http-api.md).

For model-backed `Cipher` operations over MCP or HTTP, configure a reasoning model separately from the embedding providers. That applies to explanation, chunking-strategy, and stub-review calls. `audit` is deterministic and can run without the reasoning backend.

Typical local setup for the model-backed calls:

- `OPENAI_BASE_URL=http://127.0.0.1:11434/v1`
- `OPENAI_API_KEY=ollama`
- `SYNAPSE_MODEL=openai:glm-4.7-flash:latest`

Timeout behavior for model-backed `Cipher` calls:

- default values come from the `[cipher]` section in `config/synapse.toml`
- HTTP requests can override with `timeout_seconds`
- MCP `Cipher` tools can also override with `timeout_seconds`
- timeouts and missing reasoning backends are reported explicitly instead of collapsing into generic failures

## Installation

From the Synapse repo root:

```bash
uv sync
```

Or with a local venv:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,mcp]"
```

If OpenClaw wants both MCP and the HTTP/OpenAPI app surface available in the same environment:

```bash
.venv/bin/pip install -e ".[dev,mcp,api]"
```

If OpenClaw installs dependencies itself, the minimum expectation is:

- Python `3.12+`
- the project dependencies from [pyproject.toml](../pyproject.toml)

## SQLite Vector Backend

Synapse currently uses `sqlite-vec` as its live vector backend.

OpenClaw does not need to install it separately if it installs Synapse normally:

```bash
uv sync
```

or:

```bash
.venv/bin/pip install -e ".[dev]"
```

That installs the Python `sqlite-vec` package declared in [pyproject.toml](../pyproject.toml).

Runtime behavior:

- Synapse first tries the Python package loader for `sqlite-vec`
- Synapse only falls back to a manual extension path if one is explicitly configured
- no bundled `.so` file is required in the repo anymore

If vector extension loading fails, OpenClaw should check:

- the environment actually installed `sqlite-vec`
- the Python `sqlite3` build supports extension loading
- the target database path is writable

For normal local use, OpenClaw should treat `sqlite-vec` as part of the standard Synapse install, not as a separate database setup step.

## Config Setup

Create a local config from the template:

```bash
cp config/synapse.example.toml config/synapse.toml
```

Then edit your local `config/synapse.toml` for the current machine.

Important sections:

- `[vault]`
  - `root`: markdown folder to index
- `[database]`
  - `path`: SQLite path for Synapse data
- `[index]`
  - `provider`: note-level embedding provider
  - `contextual_provider`: chunk-level embedding provider
- `[search]`
  - `mode`: `note`, `chunk`, or `hybrid`
- `[providers.embeddings.*]`
  - runtime endpoints and models

Important constraint:

- for hybrid retrieval, note and contextual providers must use matching dimensions
- the tracked example profile keeps both note and contextual embeddings at `1024`
- the tracked example chunk/search defaults are tuned for Synapse's hybrid chunking around the `0.6B` Perplexity pair

Current known-good provider examples:

- Infinity:
  - `type = "infinity"`
  - `base_url = "http://HOST:8081"`
  - `model = "perplexity-ai/pplx-embed-v1-0.6b"`
  - `dimensions = 1024`
- Infinity contextual:
  - `type = "infinity"`
  - `model = "perplexity-ai/pplx-embed-context-v1-0.6b"`
  - `context_strategy = "infinity_batch"`
- Ollama fallback:
  - `type = "ollama"`
  - `model = "argus-ai/pplx-embed-v1-0.6b:fp32"` or `nomic-embed-text:v1.5`

## Fast Path For Agents

If OpenClaw just needs Synapse working quickly, use this order:

1. copy `config/synapse.example.toml` to `config/synapse.toml`
2. set the markdown root and DB path
3. run `uv run synapse-smoke --config config/synapse.toml` to verify provider wiring against the bundled fixture vault
4. register the MCP server with [config/synapse.mcp.example.json](../config/synapse.mcp.example.json) or use the CLI directly
5. run indexing
6. run search or discovery
7. call `Cipher` only when reasoning or maintenance review is needed

## MCP Server Configuration

Most MCP clients want a `mcpServers` block, not just a Python module path.

Recommended launch pattern:

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

Why this shape:

- `synapse-mcp` is the stable entrypoint
- `SYNAPSE_CONFIG` sets the default Synapse runtime config and is required at MCP server startup
- tools can still override `vault_root` and `db_path` per call when needed

## HTTP API Configuration

For web-facing integrations, run the API server directly:

```bash
uv run synapse-api
```

OpenAPI documents:

- `http://127.0.0.1:8765/openapi.json`
- `http://127.0.0.1:8765/docs`

Tracked contract:

- [docs/openapi.json](openapi.json)

## CLI Workflow

### 0. Dry-run Synapse first

```bash
uv run synapse-smoke --config config/synapse.toml
```

What this does:

- uses the bundled fixture vault instead of the target vault
- creates a fresh temporary DB by default
- runs health, indexing, search, discovery, validation, and gardener dry-run
- optionally runs one model-backed `Cipher` explanation step when the reasoning env is configured

### 1. Index a markdown folder

```bash
uv run synapse-index \
  --config config/synapse.toml \
  --cortex /path/to/markdown \
  --db /path/to/synapse.sqlite
```

What this does:

- scans markdown files
- extracts metadata
- creates note-level embeddings
- creates chunk-level embeddings
- stores vectors and metadata in SQLite

### 2. Search semantically

```bash
uv run synapse-search \
  --config config/synapse.toml \
  --db /path/to/synapse.sqlite \
  --mode hybrid \
  "find weak signals across notes"
```

Modes:

- `note`: broad thematic retrieval
- `chunk`: precise section retrieval
- `hybrid`: note shortlist plus chunk evidence

### 3. Discover hidden relationships

```bash
uv run synapse-discover \
  --config config/synapse.toml \
  --db /path/to/synapse.sqlite \
  --threshold 0.20 \
  --top-k 3 \
  --max 20
```

Discovery scoring currently combines:

- semantic similarity
- metadata overlap
- graph overlap from wikilinks

Current scoring details:

- composite score = `min(1.0, 0.75 * semantic_similarity + metadata_score + graph_score)`
- metadata score is capped at `0.18` from tag overlap, frontmatter overlap, and title-token overlap
- graph score is capped at `0.16` from shared wikilink neighbors and direct title-bridge signals
- service-backed discovery defaults to `0.20`, while the standalone CLI currently defaults to `0.65`
- agents should set `threshold` explicitly instead of relying on a surface-specific default

### 4. Validate and garden

```bash
uv run synapse-validate --config config/synapse.toml --db /path/to/synapse.sqlite
uv run synapse-garden --config config/synapse.toml --db /path/to/synapse.sqlite
```

`synapse-garden` is now proposal-first:

- it sends broken-link stub candidates through `Cipher`
- it prints approved and skipped stub proposals
- it only writes files when run with `--apply`

## Python API Workflow

For agents that want structured control, use the Python APIs instead of parsing CLI text.

### Indexing

```python
from pathlib import Path

from synapse.embeddings import EmbeddingClient
from synapse.index import Indexer
from synapse.settings import load_settings
from synapse.vector_store import create_vector_store

settings = load_settings(Path("config/synapse.toml"))
store = create_vector_store(settings)

note_embedder = EmbeddingClient.from_provider(
    settings.embedding_provider(settings.index.provider)
)
chunk_embedder = EmbeddingClient.from_provider(
    settings.embedding_provider(settings.index.contextual_provider)
)

indexer = Indexer(
    db=store,
    cortex_path=Path("/path/to/markdown"),
    note_embedding_client=note_embedder,
    chunk_embedding_client=chunk_embedder,
    min_chunk_chars=settings.index.min_chunk_chars,
    max_chunk_chars=settings.index.max_chunk_chars,
    target_chunk_tokens=settings.index.target_chunk_tokens,
    max_chunk_tokens=settings.index.max_chunk_tokens,
    chunk_overlap_chars=settings.index.chunk_overlap_chars,
    chunk_strategy=settings.index.chunk_strategy,
)

stats = indexer.index_all()
print(stats)
```

Reindex behavior today:

- files are tracked by relative path within the configured markdown root
- unchanged files are skipped by content hash
- changed files update the document record, delete the previous stored chunks for that path, and insert fresh note and chunk rows
- reusing the same SQLite DB across different markdown roots can leave stale documents from the old root behind, because missing old paths are not pruned automatically
- chunk identity across repeated reindex runs is replacement-based today; finer-grained repair policy is still a future improvement
- for clean end-to-end runs, prefer a fresh DB per vault root or explicitly remove stale documents before reusing a shared DB

### Search

```python
from pathlib import Path

from synapse.embeddings import EmbeddingClient
from synapse.search import Searcher
from synapse.settings import load_settings
from synapse.vector_store import create_vector_store

settings = load_settings(Path("config/synapse.toml"))
store = create_vector_store(settings)

searcher = Searcher(
    db=store,
    note_embedding_client=EmbeddingClient.from_provider(
        settings.embedding_provider(settings.search.provider)
    ),
    chunk_embedding_client=EmbeddingClient.from_provider(
        settings.embedding_provider(settings.index.contextual_provider)
    ),
    search_settings=settings.search,
)

results = searcher.search(
    "find hidden relationships across markdown notes",
    limit=5,
    mode="hybrid",
)
print(results)
```

### Discovery

```python
from pathlib import Path

from synapse.discovery import find_discoveries
from synapse.settings import load_settings
from synapse.vector_store import create_vector_store

settings = load_settings(Path("config/synapse.toml"))
store = create_vector_store(settings)

discoveries = find_discoveries(
    store,
    threshold=0.20,
    top_k=3,
    max_total=10,
)
print(discoveries)
```

## `Cipher` Workflow

OpenClaw should treat `Cipher` as a structured reasoning service, not as a place to hide retrieval logic.

Use Synapse first to gather deterministic evidence, then call `Cipher`.

### Supported requests now

- `AuditVaultRequest`
- `ExplainConnectionRequest`
- `SuggestChunkingStrategyRequest`

Implementation:

- [synapse/cipher_service.py](../synapse/cipher_service.py)

### Example: audit a vault

```python
import asyncio
from pathlib import Path

from synapse.cipher_service import AuditVaultRequest, CipherDeps, CipherService

async def main():
    service = CipherService()
    response = await service.handle(
        AuditVaultRequest(mode="audit"),
        CipherDeps(
            cortex_path=Path("/path/to/markdown"),
            synapse_db=Path("/path/to/synapse.sqlite"),
        ),
    )
    print(response.model_dump())

asyncio.run(main())
```

### Example: explain a discovered connection

```python
import asyncio
from pathlib import Path

from synapse.cipher_service import CipherDeps, CipherService, ExplainConnectionRequest

async def main():
    service = CipherService()
    response = await service.handle(
        ExplainConnectionRequest(
            doc_a="notes/agency-memory.md",
            doc_b="notes/weak-signals.md",
        ),
        CipherDeps(
            cortex_path=Path("/path/to/markdown"),
            synapse_db=Path("/path/to/synapse.sqlite"),
        ),
    )
    print(response.model_dump())

asyncio.run(main())
```

## Recommended OpenClaw Control Loop

Use this loop:

1. ensure Synapse is installed
2. ensure `config/synapse.toml` points at the target markdown folder and DB
3. run `synapse-smoke` before touching the target vault
4. run indexing if the DB is missing or stale
5. run search for user-facing retrieval tasks
6. run discovery for maintenance or knowledge-graph improvement tasks
7. send structured findings to `Cipher` for explanation or audit
8. perform file changes only through explicit deterministic actions

## Environment Variables

Synapse can be driven by config, but agents may also override at runtime.

Common overrides:

- `SYNAPSE_CONFIG`
- `SYNAPSE_EMBEDDING_PROVIDER`
- `SYNAPSE_EMBEDDING_MODEL`
- `SYNAPSE_EMBEDDING_BASE_URL`
- `SYNAPSE_EMBEDDING_DIMENSIONS`

For `Cipher`, the reasoning model currently follows the OpenAI-compatible environment expected by `pydantic-ai`, for example:

- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`

## Operational Notes

- Synapse is generic markdown-first. Do not assume Obsidian-only behavior.
- `sqlite-vec` is the current supported vector backend.
- `LanceDB` is planned, not live.
- Infinity contextual behavior currently uses batch embeddings over `/embeddings`, not Perplexity's nested contextual endpoint. Native contextual requests exist for `openai_compatible` providers, but that is not the default Synapse profile.
- Discovery thresholds are still being tuned across corpora. Treat them as heuristics, not hard guarantees.
- `Cipher` audit is deterministic. Explanation, chunking strategy, and stub review are model-backed.
- Synapse can run fully local when the configured providers point at local Infinity or Ollama endpoints, but provider endpoints may also be remote.
- `config/synapse.toml` is intended to stay local and is gitignored.
- `Cipher` is safe to use for audit and explanation now, but vector-index audit and repair policy are still incomplete.
- `synapse-smoke` uses a fresh DB by default and refuses to reuse an existing DB path unless explicitly told to do so.

## Minimal Agent Checklist

- install Synapse into a local venv
- create `config/synapse.toml`
- set markdown root and SQLite DB path
- configure at least one embedding provider
- run `synapse-smoke`
- run `synapse-index`
- run `synapse-search` or `synapse-discover`
- call `CipherService` only after deterministic retrieval has produced evidence

## Related Docs

- [README.md](../README.md)
- [docs/cipher-interface.md](cipher-interface.md)
- [docs/mcp-requirements.md](mcp-requirements.md)
- [docs/http-api.md](http-api.md)
