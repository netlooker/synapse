# SYNAPSE

> Semantic shadow infrastructure for markdown vaults.

Synapse is a vault-native retrieval engine for people who keep their memory in markdown.

Point it at any markdown folder, let it slice documents into meaningful sections, embed them, index them, and surface connections that normal search will never catch. The goal is not just "RAG over files." The goal is a high-signal memory system that can trace hidden lines between scattered fragments of thought.

## Why It Exists

Most note systems fail in the same place:

- keyword search only finds what you already know to ask for
- links depend on human discipline and memory
- related ideas stay fragmented across dozens of notes
- weak signals never get promoted into explicit knowledge

Synapse is designed to work like a semantic layer over a markdown corpus:

- retrieve notes by meaning, not wording
- detect unlinked but related ideas
- help maintain graph integrity
- support an agentic librarian that can audit, suggest, and eventually repair knowledge structures

## The Vibe

Think:

- local markdown vault
- vector memory layer
- cybernetic librarian guarding the archive
- retrieval tuned for signal, not noise

This is not a chatbot wearing a notes app as a hat.

It is an indexing and discovery system for operators who want their vault to behave more like a living memory substrate.

## What Synapse Is Now

Synapse has moved from an earlier vault-specific prototype to a generic markdown retrieval engine with:

- pluggable embedding providers
- pluggable vector backends
- typed settings via `config/synapse.toml`
- note-level and chunk-level retrieval
- token-aware heading/hybrid chunking
- contextual embeddings for section-aware search
- metadata-aware reranking and discovery scoring
- a Librarian agent, `Cipher`, acting as the gatekeeper for markdown and vector memory

External-agent setup guidance lives at [docs/openclaw-integration.md](docs/openclaw-integration.md).
MCP runtime requirements live at [docs/mcp-requirements.md](docs/mcp-requirements.md).
A tracked MCP client example lives at [config/synapse.mcp.example.json](config/synapse.mcp.example.json).
HTTP/OpenAPI guidance for app integration lives at [docs/http-api.md](docs/http-api.md).
The tracked OpenAPI contract lives at [docs/openapi.json](docs/openapi.json).

## Why Perplexity Embeddings Matter

Perplexity's embedding models are a major upgrade for this kind of system.

`pplx-embed-v1`
- strong general semantic retrieval
- useful for note-level similarity and broad clustering

`pplx-embed-context-v1`
- embeds document chunks with awareness of surrounding document context
- useful for section retrieval and hidden-link discovery across notes

Why this matters:

- small chunks are better for retrieval precision
- but small chunks often lose the larger note context
- contextual embeddings restore that missing context without forcing giant chunks

That gives Synapse a path toward "RAG on steroids":

- precise chunk retrieval
- document-aware semantics
- cross-note discovery
- better evidence for downstream reasoning agents

## Current Status

Current codebase includes:

- generic markdown-folder indexing
- sqlite-vec storage behind a `VectorStore` seam
- note-level and contextual chunk-level embeddings
- semantic search with `note`, `chunk`, and `hybrid` modes
- metadata-aware reranking using tags, frontmatter, titles, paths, and wikilinks
- discovery scoring that combines semantic, metadata, and graph signals
- validation and gardening utilities
- a typed `CipherService` facade with lazy agent initialization

Recently verified live:

- Infinity-served `perplexity-ai/pplx-embed-v1-4b`
- Infinity-served `perplexity-ai/pplx-embed-context-v1-4b`
- end-to-end indexing, hybrid search, and discovery against the generic fixture vault

## Architecture

Synapse is being split into two layers.

### 1. Retrieval Engine

Deterministic Python services for:

- scanning markdown folders
- parsing metadata
- chunking notes
- embedding chunks and notes
- storing vectors and metadata
- semantic search and discovery

### 2. Librarian Layer

An agent shell over those services.

`Cipher` should reason about:

- which discoveries matter
- which links are likely missing
- what should be repaired or reindexed
- where the archive is drifting out of shape

But the actual file operations and index mutations stay in normal application code so the system remains testable and safe.

## Transport Interfaces

Synapse now has two external integration paths:

- MCP for agents and tool-using runtimes
- HTTP/OpenAPI for PWAs, dashboards, and other web clients

Both transports wrap the same Synapse service layer so indexing, search, discovery, validation, and `Cipher` do not drift across interfaces.

The interfaces are intentionally aligned:

- core retrieval exists over both MCP and HTTP
- `Cipher` audit/explain/chunking/stub-review exists over both MCP and HTTP
- reasoning-model configuration is only required for the `Cipher` operations
- model-backed `Cipher` operations use configurable timeouts and return structured timeout/dependency errors

## Configuration

Synapse now uses:

- a tracked template: [config/synapse.example.toml](config/synapse.example.toml)
- a local runtime config: `config/synapse.toml` (gitignored)

Default provider setup is optimized for Perplexity `4B` embeddings served locally through Infinity, with Ollama as a fallback.

Current default profile:

- note embeddings: `perplexity-ai/pplx-embed-v1-4b`
- contextual chunk embeddings: `perplexity-ai/pplx-embed-context-v1-4b`
- fallback embeddings: `nomic-embed-text:v1.5`
- `Cipher` timeout defaults configured in `[cipher]`

Example:

```toml
[providers.embeddings.default]
type = "infinity"
model = "perplexity-ai/pplx-embed-v1-4b"
base_url = "http://127.0.0.1:8081"
dimensions = 2560

[providers.embeddings.contextual]
type = "infinity"
model = "perplexity-ai/pplx-embed-context-v1-4b"
base_url = "http://127.0.0.1:8081"
dimensions = 2560

[providers.embeddings.fallback]
type = "ollama"
model = "nomic-embed-text:v1.5"
base_url = "http://127.0.0.1:11434"
dimensions = 768

[cipher]
default_timeout_seconds = 45
explain_timeout_seconds = 45
chunking_timeout_seconds = 30
stub_review_timeout_seconds = 45
```

Override behavior is simple:

1. CLI args
2. environment variables
3. `config/synapse.toml`
4. built-in defaults

Bootstrap a local config:

```bash
cp config/synapse.example.toml config/synapse.toml
```

MCP clients can register Synapse with the example server config in [config/synapse.mcp.example.json](config/synapse.mcp.example.json).

## Installation

```bash
uv sync
```

Or:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

For MCP plus the web API:

```bash
.venv/bin/pip install -e ".[dev,mcp,api]"
```

For the web API:

```bash
.venv/bin/pip install -e ".[api]"
```

## Public Status

Synapse is ready to be shared as an experimental open-source project.

That means:

- the main indexing, search, and discovery path works
- the architecture is stable enough for outside contributors to read and extend
- some edges are still intentionally rough while the retrieval and agent layers are being tuned

Current limitations:

- `sqlite-vec` is the only live vector backend today
- discovery thresholds are still heuristic and corpus-dependent
- `Cipher` is solid for audit and explanation, but vector-index audit and repair policy are still incomplete
- native nested Perplexity contextual API flow is not yet the common production path

## Development

Run focused tests:

```bash
uv run pytest -q tests/test_settings.py
```

Run the project test suite:

```bash
uv run pytest -q
```

Run the main focused suite used during the refactor:

```bash
uv run pytest -q \
  tests/test_settings.py \
  tests/test_index.py \
  tests/test_search.py \
  tests/test_db.py \
  tests/test_discovery.py \
  tests/test_embeddings.py \
  tests/test_cipher_service.py
```

## CLI

### Index a markdown folder

```bash
uv run synapse-index --config config/synapse.toml --cortex ~/notes --db ~/notes/.synapse.sqlite
```

Useful overrides:

```bash
uv run synapse-index \
  --config config/synapse.toml \
  --provider default \
  --base-url http://127.0.0.1:8081 \
  --model perplexity-ai/pplx-embed-v1-4b
```

### Search semantically

```bash
uv run synapse-search --config config/synapse.toml --db ~/notes/.synapse.sqlite "distributed memory and weak links"
```

Search modes:

```bash
uv run synapse-search --config config/synapse.toml --db ~/notes/.synapse.sqlite --mode note "semantic memory"
uv run synapse-search --config config/synapse.toml --db ~/notes/.synapse.sqlite --mode chunk "contextual retrieval"
uv run synapse-search --config config/synapse.toml --db ~/notes/.synapse.sqlite --mode hybrid "weak signals across notes"
```

### Discover hidden relationships

```bash
uv run synapse-discover --config config/synapse.toml --db ~/notes/.synapse.sqlite --threshold 0.20 --max 10
```

### Validate graph integrity

```bash
uv run synapse-validate --config config/synapse.toml --db ~/notes/.synapse.sqlite
```

### Grow missing stubs

```bash
uv run synapse-garden --config config/synapse.toml --db ~/notes/.synapse.sqlite --cortex ~/notes
```

Apply only after Cipher review:

```bash
uv run synapse-garden --config config/synapse.toml --db ~/notes/.synapse.sqlite --cortex ~/notes --apply
```

## License

Synapse is released under the [MIT License](LICENSE).

## Design Principles

- Markdown first
- Retrieval before generation
- Deterministic mechanics under agentic reasoning
- Configurable providers
- High signal over maximal recall
- Local-first when possible, provider-flexible when useful
- Generic markdown folder support first, product-specific conventions second

## Near-Term Roadmap

- tune discovery weights on larger real-world corpora
- add vector index audit operations to `Cipher`
- add LanceDB as a second vector backend
- benchmark `4B` vs `0.6B` profiles on larger vaults
- tighten chunk identity and multi-run reindex behavior

## In One Sentence

Synapse is a cybernetic memory layer for markdown vaults: a system that indexes, retrieves, and connects ideas across notes so the archive can expose patterns that human attention alone will miss.
