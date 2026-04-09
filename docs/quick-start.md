# Quick Start

This is the fastest path from clone to first search.

## 1. Install Synapse

```bash
uv sync
```

Or:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## 2. Create a local settings file

```bash
cp config/synapse.example.toml config/synapse.toml
```

## 3. Edit `config/synapse.toml`

Set at least:

- `[vault].root` to your markdown folder
- `[database].path` to the SQLite file Synapse should use
- `[providers.embeddings.default]` to a reachable embedding endpoint
- `[providers.embeddings.contextual]` if you want contextual chunk retrieval

If you want the default local profile from the template to work, make sure you have one of these running:

- Infinity serving Perplexity embedding models on `http://127.0.0.1:8081`
- Ollama serving the fallback embedding model on `http://127.0.0.1:11434`

Infinity note:

- for the shipped `pplx-embed-v1-0.6b` and `pplx-embed-context-v1-0.6b` profile, prefer `float32` on Blackwell-class DGX systems
- an observed `float16` deployment returned invalid `null` embeddings for real markdown notes while still passing short health probes
- after changing model size or dtype, verify with `uv run synapse-smoke --config config/synapse.toml --with-cipher never`

If you only want core indexing and search, you do not need to configure a reasoning model. `Cipher` is only required for reasoning-backed operations such as explanation and maintenance review.

## 4. Index your markdown folder

```bash
uv run synapse-index \
  --config config/synapse.toml \
  --vault-root ~/notes \
  --db ~/notes/.synapse.sqlite
```

## 5. Run a semantic search

```bash
uv run synapse-search \
  --config config/synapse.toml \
  --db ~/notes/.synapse.sqlite \
  --mode research \
  "weak signals across notes"
```

Available search modes are `source`, `note`, `evidence`, and `research`. `research` is the default mixed retrieval surface.

## 6. Explore hidden relationships

```bash
uv run synapse-discover \
  --config config/synapse.toml \
  --db ~/notes/.synapse.sqlite \
  --threshold 0.20 \
  --max 10
```

## Next

- Main project overview: [README.md](../README.md)
- Technical architecture: [docs/architecture.md](architecture.md)
- Agent onboarding: [docs/agent-introduction.md](agent-introduction.md)
- OpenClaw integration: [docs/openclaw-integration.md](openclaw-integration.md)
- HTTP/OpenAPI integration: [docs/http-api.md](http-api.md)
- MCP requirements: [docs/mcp-requirements.md](mcp-requirements.md)
