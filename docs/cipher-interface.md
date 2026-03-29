# Cipher Interface

## Purpose

`Cipher` is the Librarian agent for Synapse.

It is intended to act as the reasoning layer above deterministic Synapse services:

- markdown audit
- vector index audit
- hidden-link review
- maintenance planning
- controlled repair actions

The goal is to make `Cipher` usable by external agents such as OpenClaw without requiring them to understand Synapse internals.

## Current Status

A stable typed contract now exists.

Current implementation lives in [synapse/cipher_service.py](../synapse/cipher_service.py).

Current transport surfaces:

- MCP tools through [synapse/mcp_server.py](../synapse/mcp_server.py)
- HTTP/OpenAPI endpoints through [synapse/web_api.py](../synapse/web_api.py)

Current strengths:

- lazy agent initialization
- typed request/response models
- deterministic vault audit path
- connection explanation path
- chunking-strategy advice path
- stub-review path
- aligned MCP and HTTP exposure

Current gaps:

- repair mode is still advisory and does not mutate files or repair vector state automatically
- vector index audit is not yet complete
- external-agent coverage is still growing

## Intended Integration Model

External agents should interact with `Cipher` through task-oriented operations, not ad hoc prompts.

Currently implemented operations:

- `audit_vault`
- `suggest_chunking_strategy`
- `explain_connection`
- `review_stub_candidates`

Planned operations:

- `review_discoveries`
- `plan_repairs`
- `repair_links`
- `audit_vector_index`

## Current Capability Contract

### 1. Audit Vault

Input:

```json
{
  "op": "audit_vault",
  "vault_path": "/path/to/vault",
  "db_path": "/path/to/synapse.sqlite",
  "mode": "audit"
}
```

Current behavior:

- scans markdown files for broken wikilinks
- suggests `repair_links` when broken links exist
- suggests `reindex_documents` when the configured DB path does not exist
- does not currently perform repair actions, even when `mode` is `"repair"`

Output:

```json
{
  "status": "ok",
  "summary": "2 broken links, 1 stale index candidate",
  "broken_links": [
    {
      "source_path": "notes/foo.md",
      "target_link": "Bar"
    }
  ],
  "stale_documents": [],
  "suggested_actions": [
    "repair_links",
    "reindex_documents"
  ]
}
```

### 2. Explain Connection

Input:

```json
{
  "op": "explain_connection",
  "doc_a": "notes/a.md",
  "doc_b": "notes/b.md"
}
```

Output:

```json
{
  "status": "ok",
  "explanation": "Both notes revolve around contextual retrieval and maintenance safety.",
  "keywords": [
    "contextual retrieval",
    "maintenance",
    "semantic memory"
  ]
}
```

### 3. Suggest Chunking Strategy

Input:

```json
{
  "op": "suggest_chunking_strategy",
  "model_info": "perplexity-ai/pplx-embed-context-v1-4b, 2560 dimensions, 32k context"
}
```

Output:

```json
{
  "status": "ok",
  "max_chunk_size": 2200,
  "min_chunk_size": 360,
  "rationale": "Use medium chunks with room for contextual reranking."
}
```

### 4. Review Stub Candidates

Input:

```json
{
  "op": "review_stub_candidates",
  "stub_dir": "entities",
  "candidates": [
    {
      "target_link": "Semantic Memory",
      "source_paths": [
        "notes/a.md"
      ],
      "suggested_path": "entities/Semantic Memory.md"
    }
  ]
}
```

Output:

```json
{
  "status": "ok",
  "reviews": [
    {
      "target_link": "Semantic Memory",
      "action": "create_stub",
      "confidence": 0.86,
      "rationale": "This is a reusable concept note.",
      "suggested_path": "entities/Semantic Memory.md"
    }
  ]
}
```

## Planned Capability Contract

The following operations are part of the intended direction, but are not implemented in the current `CipherService` contract yet.

### 5. Review Discoveries

Input:

```json
{
  "op": "review_discoveries",
  "vault_path": "/path/to/vault",
  "db_path": "/path/to/synapse.sqlite",
  "discoveries": [
    {
      "source_path": "notes/a.md",
      "target_path": "notes/b.md",
      "similarity": 0.81
    }
  ]
}
```

Output:

```json
{
  "status": "ok",
  "reviews": [
    {
      "source_path": "notes/a.md",
      "target_path": "notes/b.md",
      "decision": "promote",
      "confidence": 0.86,
      "explanation": "These notes describe the same retrieval pattern from different operational angles.",
      "suggested_links": [
        "[[Note B]]"
      ]
    }
  ]
}
```

### 6. Plan Repairs

Input:

```json
{
  "op": "plan_repairs",
  "vault_path": "/path/to/vault",
  "db_path": "/path/to/synapse.sqlite",
  "issues": [
    {
      "type": "broken_link",
      "source_path": "notes/foo.md",
      "target_link": "Bar"
    }
  ]
}
```

Output:

```json
{
  "status": "ok",
  "plan": [
    {
      "action": "replace_link",
      "source_path": "notes/foo.md",
      "old_link": "Bar",
      "new_link": "Bar Protocol",
      "confidence": 0.74
    }
  ],
  "requires_review": true
}
```

## Recommended Runtime Shape

Other agents should not import transport-specific internals directly.

They should call a facade such as:

- `CipherService.handle(request: CipherRequest, deps: CipherDeps) -> CipherResponse`

Where:

- Synapse services provide deterministic facts
- `Cipher` reasons over those facts
- all write actions remain explicit and auditable

Model requirements today:

- `audit_vault` is deterministic and does not need a reasoning model
- `explain_connection`, `suggest_chunking_strategy`, and `review_stub_candidates` are model-backed
- model-backed requests accept per-request `timeout_seconds` overrides over the defaults in `[cipher]`

## For OpenClaw

OpenClaw-style usage should look like:

1. ask Synapse for discoveries, broken links, or index status
2. send those structured results to `Cipher`
3. receive a structured review or repair plan
4. execute deterministic actions only after policy checks

OpenClaw should not depend on:

- prompt wording
- internal tool names
- environment-specific defaults
- direct filesystem assumptions inside agent-specific wrappers

## Short-Term Recommendation

External agents should now treat `Cipher` as:

- service-backed
- typed
- suitable for audit, explanation, chunking advice, and stub review today

Still to improve:

- richer repair policies
- vector-index audit operations
- broader integration coverage

## Alignment

`Cipher` is now exposed consistently across both transport layers.

HTTP endpoints:

- `POST /cipher/audit`
- `POST /cipher/explain`
- `POST /cipher/chunking-strategy`
- `POST /cipher/review-stubs`

MCP tools:

- `synapse_cipher_audit`
- `synapse_cipher_explain`
- `synapse_cipher_chunking_strategy`
- `synapse_cipher_review_stubs`

This is the intended contract shape:

- deterministic Synapse services remain shared underneath
- `Cipher` remains a separate reasoning surface
- transport choice should not change the underlying behavior

This interface document matches the current Synapse architecture, especially:

- agent shell over deterministic services
- separate reasoning-model layer
- `CipherService`
- maintenance policy controls
