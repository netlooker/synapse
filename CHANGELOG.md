# Changelog

All notable changes to Synapse are documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.1] - 2026-04-11

### Fixed
- OpenAPI metadata now reports the current package version instead of the stale
  `0.1.0` value, and the tracked export has a regression test to catch future
  version drift.

## [0.3.0] - 2026-04-10

This release closes the gap called out in the 0.2.0 notes ("no MCP parity
yet") by exposing the full compiled knowledge layer — the review, apply, and
inspection workflow operators drive through the admin console — over MCP.
Agent-driven and human-driven flows now share one code path. The layer is
still opt-in: set `knowledge.enabled = true` (or `SYNAPSE_KNOWLEDGE_ENABLED=true`)
to turn it on.

### Added
- **MCP parity for the compiled knowledge layer.** Nine new tools wrap the
  same `service_api` entry points the admin console already uses, so
  agent-driven and human-driven flows share one code path:
  - `synapse_ingest_bundle` — ingest a prepared research source bundle JSON.
  - `synapse_knowledge_overview` — managed root, status counts, recent proposals.
  - `synapse_knowledge_compile_bundle` — turn an ingested bundle into pending
    source_summary proposals.
  - `synapse_knowledge_list_proposals` — filter the review queue by status.
  - `synapse_knowledge_get_proposal` — full proposal detail (frontmatter, body,
    supporting refs, reviewer action).
  - `synapse_knowledge_apply_proposal` — write the managed note, update
    `index.md`/`log.md`, and reindex.
  - `synapse_knowledge_reject_proposal` — mark a proposal rejected and append
    the reason to `log.md`.
  - `synapse_knowledge_bundle_detail` — bundle metadata plus per-source
    proposal/applied counts.
  - `synapse_knowledge_source_detail` — normalized source metadata with stored
    segments and related proposals.
  - Every knowledge tool enforces the same `knowledge.enabled` feature gate as
    the HTTP API — when disabled, the tool raises a structured bad-request
    error pointing operators at the setting.

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

[Unreleased]: https://github.com/netlooker/synapse/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/netlooker/synapse/releases/tag/v0.3.1
[0.3.0]: https://github.com/netlooker/synapse/releases/tag/v0.3.0
[0.2.0]: https://github.com/netlooker/synapse/releases/tag/v0.2.0
