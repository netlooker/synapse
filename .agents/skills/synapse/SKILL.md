---
name: synapse
description: Semantic search, discovery, reasoning, research-bundle ingest, and compiled-knowledge review over markdown vaults via Synapse MCP tools.
user-invocable: true
disable-model-invocation: false
---

# Synapse MCP

Synapse is a semantic retrieval, discovery, and compiled-knowledge engine for markdown knowledge bases. It indexes markdown folders into embeddings, exposes deterministic search and validation over MCP, and can ingest prepared research bundles into reviewable `source_summary` proposals under a managed knowledge subtree.

This skill documents the current MCP surface shipped by the `synapse` repo itself.

## Available tools

### Deterministic retrieval

| Tool | Purpose | Key params |
|------|---------|------------|
| `synapse_health` | Check runtime readiness, DB status, provider config | optional overrides |
| `synapse_index` | Index a markdown folder into the vector store | `vault_root`, `db_path` |
| `synapse_search` | Semantic search across indexed content | `query`, `mode`, `limit`, optional `bundle_id` |
| `synapse_discover` | Find unlinked but semantically related documents | `threshold`, `max_total` |
| `synapse_validate` | Report broken `[[wikilinks]]` and vector integrity in indexed vault | optional overrides |
| `synapse_health_for_workspace` | Check readiness for the configured active workspace | `workspace` |
| `synapse_index_for_workspace` | Index the configured active workspace | `workspace` |
| `synapse_search_for_workspace` | Search the configured active workspace | `workspace`, `query`, `mode`, `limit`, optional `bundle_id` |

### Strict-shape local-model facade

| Tool | Purpose | Required params |
|------|---------|-----------------|
| `synapse_health_simple` | Minimal health probe | `vault_root`, `db_path` |
| `synapse_index_simple` | Minimal index call | `vault_root`, `db_path` |
| `synapse_search_simple` | Minimal search call | `query`, `db_path`, optional `bundle_id` |

### Reasoning via Cipher

| Tool | Purpose | Key params |
|------|---------|------------|
| `synapse_cipher_health` | Report Cipher runtime requirements and readiness | optional overrides |
| `synapse_cipher_audit` | Audit vault integrity | `mode` |
| `synapse_cipher_explain` | Explain why two documents are related | `doc_a`, `doc_b` |
| `synapse_cipher_chunking_strategy` | Recommend chunking parameters for a model | optional overrides |
| `synapse_cipher_review_stubs` | Review proposed stub notes before creation | candidates |

### Compiled knowledge layer

| Tool | Purpose | Required params |
|------|---------|-----------------|
| `synapse_ingest_bundle` | Ingest a prepared research source bundle JSON | `bundle_path` |
| `synapse_knowledge_overview` | Managed-root status, counts, recent proposals | — |
| `synapse_knowledge_compile_bundle` | Turn an ingested bundle into pending `source_summary` proposals | `bundle_id` |
| `synapse_knowledge_list_proposals` | Filter review queue by `status` | optional `status`, `limit` |
| `synapse_knowledge_get_proposal` | Full proposal detail | `proposal_id` |
| `synapse_knowledge_apply_proposal` | Apply a pending proposal | `proposal_id` |
| `synapse_knowledge_reject_proposal` | Reject a pending proposal and append reason to `log.md` | `proposal_id` |
| `synapse_knowledge_revert_proposal` | Revert an applied proposal back to pending review | `proposal_id` |
| `synapse_knowledge_bundle_detail` | Bundle metadata plus per-source proposal counts | `bundle_id` |
| `synapse_knowledge_source_detail` | Normalized source metadata, stored segments, related proposals | `bundle_id`, `source_id` |

## Search modes

- `research`: blended source-first retrieval, usually the default and best starting point
- `source`: return source-oriented matches
- `note`: return note-oriented matches
- `evidence`: return narrow evidence matches

Prefer `research` unless the task specifically wants note-only or evidence-only output.
Pass plain user text directly as `query`, including multi-word phrases such as `note taking`; Synapse normalizes it for lexical search internally.

## Corpus-scoped retrieval

Use unscoped search for whole-vault discovery and open-ended retrieval.

Use `bundle_id` filtering for corpus evaluations, source-pack QA, and questions that must be answered from a specific ingested bundle. Without a bundle scope, older unrelated bundles can compete with the target corpus.

CLI example:

```bash
synapse-python -m synapse.search \
  --config /config/synapse.toml \
  --db /data/workspace/vault/.synapse.sqlite \
  --bundle-id km-final-selected \
  --mode source \
  "external cognition"
```

MCP shape:

```json
{
  "query": "external cognition",
  "mode": "source",
  "db_path": "/data/workspace/vault/.synapse.sqlite",
  "bundle_id": "km-final-selected"
}
```

## Knowledge workflow

1. Ingest a prepared bundle with `synapse_ingest_bundle`.
2. Compile it with `synapse_knowledge_compile_bundle`.
3. Review candidates with `synapse_knowledge_list_proposals` and `synapse_knowledge_get_proposal`.
4. Apply, reject, or revert with the proposal action tools.
5. Use `synapse_knowledge_overview`, bundle detail, and source detail for provenance and status.

Guardrails:

- do not hand-edit the managed root
- use `synapse_knowledge_revert_proposal` to undo an applied note while preserving audit history
- rejected proposals stay visible as audit records
- do not run manual SQL migrations before knowledge tools; opening the store through Synapse should apply supported DB schema migrations automatically

## Bundle ingest guidance

- bundles may omit optional metadata fields
- ingest accepts `sources`, `prepared_sources`, or a single `source`
- source text can arrive through `text`, `content`, `body`, or `markdown`
- duplicate sources are skipped by default using URL identity and content-hash checks
- pass `replace_existing=true` to replace an already ingested duplicate source

## Embedding behavior

- Synapse tries the configured provider first
- if a compatible named `fallback` provider exists, it tries that next
- if remote providers fail, it falls back to a local in-process embedding adapter

This keeps indexing and search available during provider outages, though retrieval quality may differ from the primary model.

## Vector integrity checks

`synapse_validate` returns a `vector_integrity` section with segment/vector counts, orphan and missing vector counts, `shadow_rowids_id_null_count`, the linkage key, and a status.

`vec_segments_rowids` is an sqlite-vec internal shadow table. Synapse links segments through `segments.id` and `vec_segments.segment_id`; `vec_segments_rowids.rowid` mirrors the relevant row identity. NULL values in `vec_segments_rowids.id` alone are informational when orphan and missing counts are zero.

Until runtime diagnostics are available in older deployments, use these SQL checks:

```sql
SELECT COUNT(*) AS orphan_vectors
FROM vec_segments_rowids vr
LEFT JOIN segments s ON s.id = vr.rowid
WHERE s.id IS NULL;

SELECT COUNT(*) AS missing_vectors
FROM segments s
LEFT JOIN vec_segments_rowids vr ON vr.rowid = s.id
WHERE vr.rowid IS NULL;
```
