# Changelog

All notable changes to Synapse are documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-04-10

This release introduces the optional compiled knowledge layer and its operator
admin console. The feature is disabled by default: set `knowledge.enabled = true`
(or `SYNAPSE_KNOWLEDGE_ENABLED=true`) to turn it on. With the flag off, every
`/knowledge/*` and `/ui/knowledge/*` route returns `404` and no managed files are
written, so existing deployments are unaffected.

### Added
- **Compiled knowledge layer (Phase 1).** A review-gated pipeline that turns
  ingested source bundles into deterministic `source_summary` notes under a
  configurable managed subtree (default `_knowledge/`). Proposals are stored in
  SQLite (`knowledge_jobs`, `knowledge_proposals`) and are only written to disk
  after an operator approves them. Apply is atomic: the target file, `index.md`,
  and `log.md` are snapshotted before mutation and restored on any failure,
  including reindex failures.
  - `compile_bundle` produces one proposal per source in a bundle.
  - `apply_proposal` writes markdown into `{managed_root}/sources/{bundle_id}/{slug}.md`,
    updates `index.md` with relative links, appends to `log.md`, and narrowly
    re-indexes only the affected files.
  - `reject_proposal` records the decision and appends a reason to `log.md`.
  - Apply-time SHA-256 conflict detection protects against hand edits of the
    target file between compile and apply.
  - Managed paths are scoped by `bundle_id` so the same `source_id` can live
    across bundles without collision.
- **HTTP API.** New JSON routes under `/knowledge`:
  - `POST /ingest-bundle`
  - `POST /knowledge/compile/bundle`
  - `GET /knowledge/overview`
  - `GET /knowledge/proposals`
  - `POST /knowledge/proposals/{id}/apply`
  - `POST /knowledge/proposals/{id}/reject`
- **Admin console (thin server-rendered UI).** New HTML control plane under
  `/ui/knowledge/` for operators to inspect bundles, sources, and chunks, and
  to run the review/apply workflow end to end. No SPA toolchain, no Jinja2
  dependency — plain Python HTML templating.
  - `Home` — counts and recent activity overview.
  - `Sources` and `Bundle detail` — raw-input inspection with per-source
    proposal and apply counts.
  - `Source detail` — source metadata, normalized summary, stored chunks grouped
    by `summary` / `abstract` / `full_text`, and related proposals.
  - `Review queue` and `Review item` — the operator inbox and per-proposal
    decision surface with frontmatter, supporting refs, and draft markdown.
  - `Library` — applied notes only, as a confirmation view for the managed
    subtree.
  - `Operations` and `Logs` — administrative monitoring with parsed operational
    activity and access to `_knowledge/log.md`.
- **`[knowledge]` settings block** with environment override
  `SYNAPSE_KNOWLEDGE_ENABLED`, plus `managed_root`, `default_status`,
  `generated_by`, and `auto_compile_on_ingest` keys. Documented in
  `config/synapse.example.toml`.
- **Operator guide.** `docs/knowledge-admin-guide.md` walks through the full
  admin-console workflow with screenshots.
- **Bundle ingest endpoint wiring** (`POST /ingest-bundle`) surfaced through the
  shared service layer so the knowledge pipeline can run end to end over HTTP.

### Changed
- Default managed knowledge root is `_knowledge` (was previously prototyped as
  `_compiled`).
- `docs/openapi.json` regenerated to include the new knowledge and ingest
  routes.
- `.gitignore` now excludes `.claude/`.

### Notes
- The knowledge layer is strictly opt-in and has no MCP parity yet.
- All markdown bodies are rendered deterministically from already-indexed source
  fields; there is no model/Cipher dependency on the core compile/apply path.

[0.2.0]: https://github.com/netlooker/synapse/releases/tag/v0.2.0
