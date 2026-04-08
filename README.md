# SYNAPSE

> Semantic shadow infrastructure for markdown vaults.

Synapse indexes a folder of markdown notes, stores semantic embeddings, and lets you search and discover related ideas.

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
Agent onboarding guidance lives at [docs/agent-introduction.md](docs/agent-introduction.md).
Regular user setup lives at [docs/quick-start.md](docs/quick-start.md).
Architecture and system boundaries live at [docs/architecture.md](docs/architecture.md).
MCP runtime requirements live at [docs/mcp-requirements.md](docs/mcp-requirements.md).
A tracked MCP client example lives at [config/synapse.mcp.example.json](config/synapse.mcp.example.json).
HTTP/OpenAPI guidance for app integration lives at [docs/http-api.md](docs/http-api.md).
The tracked OpenAPI contract lives at [docs/openapi.json](docs/openapi.json).

## Simplest Working Setup

If you just want Synapse working with the least setup friction:

1. install Synapse with `uv sync`
2. copy [config/synapse.example.toml](config/synapse.example.toml) to `config/synapse.toml`
3. point `[vault].root` at your markdown folder
4. point `[database].path` at a writable SQLite file
5. run Ollama locally on `http://127.0.0.1:11434`
6. switch the default embedding provider in `config/synapse.toml` to the Ollama fallback provider if needed
7. run `uv run synapse-smoke --config config/synapse.toml`
8. follow [docs/quick-start.md](docs/quick-start.md) for the first index and search commands

That is the easiest way to try Synapse before moving to the stronger Infinity + Perplexity `4B` setup.

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
- metadata-aware reranking and discovery scoring
- validation and gardening utilities
- aligned MCP and HTTP/OpenAPI interfaces
- a typed `CipherService` facade

Recently verified live:

- Infinity-served Perplexity embedding models
- end-to-end indexing, hybrid search, and discovery against the generic fixture vault

For the technical map of the system, see [docs/architecture.md](docs/architecture.md).

## Configuration

Synapse now uses:

- a tracked template: [config/synapse.example.toml](config/synapse.example.toml)
- a local runtime config: `config/synapse.toml` (gitignored)

The tracked example config is optimized for `perplexity-ai/pplx-embed-v1-0.6b` and `perplexity-ai/pplx-embed-context-v1-0.6b` served through Infinity, with Ollama as a fallback.

Current default profile:

- note embeddings: `perplexity-ai/pplx-embed-v1-0.6b`
- contextual chunk embeddings: `perplexity-ai/pplx-embed-context-v1-0.6b`
- fallback embeddings: `nomic-embed-text:v1.5`
- `Cipher` timeout defaults configured in `[cipher]`
- note and contextual provider dimensions must match for hybrid retrieval; the shipped example keeps both at `1024`
- chunking defaults are tuned for Synapse's hybrid chunker, targeting medium 0.6B-sized chunks instead of directly mirroring training-time paper settings
- on Blackwell-class DGX deployments, prefer `float32` when serving the `0.6B` Perplexity pair through Infinity; an observed `float16` deployment returned invalid `null` embeddings for realistic markdown inputs even though short probe requests looked healthy

Operational check:

- after changing Infinity dtype or model size, run `uv run synapse-smoke --config config/synapse.toml --with-cipher never` before indexing a real vault

Example:

```toml
[index]
provider = "default"
contextual_provider = "contextual"
min_chunk_chars = 700
max_chunk_chars = 1400
target_chunk_tokens = 256
max_chunk_tokens = 400
chunk_overlap_chars = 120
chunk_strategy = "hybrid"

[search]
provider = "default"
limit = 5
mode = "hybrid"
candidate_multiplier = 10
note_weight = 0.5
chunk_weight = 0.5

[providers.embeddings.default]
type = "infinity"
model = "perplexity-ai/pplx-embed-v1-0.6b"
base_url = "http://127.0.0.1:8081"
dimensions = 1024

[providers.embeddings.contextual]
type = "infinity"
model = "perplexity-ai/pplx-embed-context-v1-0.6b"
base_url = "http://127.0.0.1:8081"
dimensions = 1024

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

For a step-by-step local setup, see [docs/quick-start.md](docs/quick-start.md).

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

Current operational details:

- service-backed discovery defaults to `0.20`, while the standalone CLI currently defaults to `0.65`; set the threshold explicitly when you need repeatable behavior across surfaces
- reindexing is path-based: unchanged files are skipped by content hash, and changed files replace the stored note segments for that path
- reusing one SQLite DB across different vault roots can leave stale entries behind, because indexing updates by stored path and does not currently prune paths that disappeared under an older root
- `Cipher` audit is deterministic, while explanation, chunking advice, and stub review are model-backed

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

### Dry-run Synapse

```bash
uv run synapse-smoke --config config/synapse.toml
```

This command uses the bundled fixture vault and a fresh temporary DB by default so agents can verify provider wiring and retrieval behavior without touching a real vault.

### Index a markdown folder

```bash
uv run synapse-index --config config/synapse.toml --vault-root ~/notes --db ~/notes/.synapse.sqlite
```

Useful overrides:

```bash
uv run synapse-index \
  --config config/synapse.toml \
  --provider default \
  --base-url http://127.0.0.1:8081 \
  --model perplexity-ai/pplx-embed-v1-0.6b
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
uv run synapse-garden --config config/synapse.toml --db ~/notes/.synapse.sqlite --vault-root ~/notes
```

Apply only after Cipher review:

```bash
uv run synapse-garden --config config/synapse.toml --db ~/notes/.synapse.sqlite --vault-root ~/notes --apply
```

## License

Synapse is released under the [MIT License](LICENSE).

## In One Sentence

Synapse is a cybernetic memory layer for markdown vaults: a system that indexes, retrieves, and connects ideas across notes so the archive can expose patterns that human attention alone will miss.
