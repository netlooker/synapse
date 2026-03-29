# Synapse Automation

# Default: List recipes
default:
    @just --list

# Install dependencies and setup environment
setup:
    python3 -m venv .venv
    .venv/bin/pip install -e ".[dev]"

# Run tests
test:
    .venv/bin/pytest -v

# Run full index
index:
    .venv/bin/python -m synapse.index

# Run discovery
discover threshold="0.65":
    .venv/bin/python -m synapse.discovery --threshold {{threshold}}

# Run link validation
validate:
    .venv/bin/python -m synapse.validate

# Run gardener (auto-create stubs)
garden:
    .venv/bin/python -m synapse.gardener

# Run agent-facing smoke test
smoke:
    .venv/bin/python -m synapse.smoke

# Export the tracked OpenAPI document
openapi:
    .venv/bin/python -m synapse.export_openapi
