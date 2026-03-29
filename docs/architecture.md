# Architecture

This document describes how Synapse is structured today and where the main boundaries are.

## System Shape

Synapse is a semantic retrieval and discovery engine for markdown knowledge bases.

It has three main layers:

1. deterministic retrieval services
2. a reasoning shell called `Cipher`
3. transport adapters for agents and apps

The design goal is simple:

- keep indexing, storage, and retrieval deterministic
- keep reasoning optional and layered on top
- keep transport adapters thin

## Retrieval Core

The retrieval core is plain Python application code.

It handles:

- recursive markdown file discovery
- frontmatter, tags, and wikilink extraction
- chunking
- note-level and chunk-level embeddings
- vector storage
- semantic search
- hidden-link discovery
- validation of broken links

Important modules:

- [synapse/index.py](../synapse/index.py)
- [synapse/search.py](../synapse/search.py)
- [synapse/discovery.py](../synapse/discovery.py)
- [synapse/validate.py](../synapse/validate.py)
- [synapse/db.py](../synapse/db.py)
- [synapse/vector_store.py](../synapse/vector_store.py)

## Cipher

`Cipher` is the reasoning shell over the deterministic services.

It is responsible for tasks such as:

- auditing a vault
- explaining why notes are connected
- suggesting chunking strategy
- reviewing stub-note proposals before write operations

Important module:

- [synapse/cipher_service.py](../synapse/cipher_service.py)

The intended rule is:

- deterministic mechanics live in normal application code
- reasoning stays at the decision and review layer

That keeps the project safer, easier to test, and easier to integrate with different agent runtimes.

## Transport Interfaces

Synapse exposes the same capabilities over two transport styles:

- MCP for agent runtimes
- HTTP/OpenAPI for apps, PWAs, and dashboards

Important modules:

- [synapse/mcp_server.py](../synapse/mcp_server.py)
- [synapse/web_api.py](../synapse/web_api.py)
- [synapse/service_api.py](../synapse/service_api.py)

The transport goal is alignment:

- indexing, search, discovery, and validation exist over both transports
- `Cipher` audit, explain, chunking-strategy, and stub-review exist over both transports
- the same service layer sits underneath both

## Storage And Providers

Current storage and provider design:

- vector storage uses `sqlite-vec` today
- vector access is behind a `VectorStore` seam
- embedding providers are pluggable
- note-level and contextual chunk-level embeddings are separate concerns

Important modules:

- [synapse/providers/embeddings/base.py](../synapse/providers/embeddings/base.py)
- [synapse/providers/embeddings/factory.py](../synapse/providers/embeddings/factory.py)
- [synapse/providers/embeddings/infinity.py](../synapse/providers/embeddings/infinity.py)
- [synapse/providers/embeddings/ollama.py](../synapse/providers/embeddings/ollama.py)
- [synapse/providers/embeddings/openai_compatible.py](../synapse/providers/embeddings/openai_compatible.py)

Current known-good setup:

- note embeddings from `perplexity-ai/pplx-embed-v1-4b`
- contextual chunk embeddings from `perplexity-ai/pplx-embed-context-v1-4b`
- served locally through Infinity or Ollama

## Configuration Model

Synapse uses:

- tracked template: [config/synapse.example.toml](../config/synapse.example.toml)
- local runtime file: `config/synapse.toml`

Override order:

1. CLI arguments
2. environment variables
3. `config/synapse.toml`
4. built-in defaults

Important module:

- [synapse/settings.py](../synapse/settings.py)

## Design Principles

- Markdown first
- Retrieval before generation
- Deterministic mechanics under agentic reasoning
- Configurable providers
- High signal over maximal recall
- Local-first when possible, provider-flexible when useful
- Generic markdown folder support first, product-specific conventions second

## Current Technical Status

What is already solid:

- generic markdown-folder indexing
- note-level and contextual chunk-level embeddings
- semantic search with `note`, `chunk`, and `hybrid` modes
- metadata-aware reranking
- discovery scoring that combines semantic, metadata, and graph signals
- MCP and HTTP/OpenAPI aligned over the same service layer
- typed `CipherService` facade

What is still intentionally incomplete:

- `sqlite-vec` is the only live vector backend today
- discovery thresholds are still heuristic and corpus-dependent
- vector-index audit and repair policy inside `Cipher` is still incomplete
- native nested Perplexity contextual API flow is not yet the common production path

## Near-Term Direction

- tune discovery weights on larger real-world corpora
- add vector index audit operations to `Cipher`
- add LanceDB as a second vector backend
- benchmark `4B` vs `0.6B` profiles on larger vaults
- tighten chunk identity and multi-run reindex behavior
