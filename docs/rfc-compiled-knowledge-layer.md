# RFC: Compiled Knowledge Layer For Synapse

Status: Draft

## Summary

This RFC proposes an optional compiled knowledge layer on top of Synapse's existing retrieval core.

The goal is not to turn Synapse into "Obsidian with vibes" or to replace vector retrieval with a giant context window. The goal is to let Synapse ingest source material, maintain auditable markdown knowledge artifacts derived from that material, and use the existing search, discovery, and validation stack to keep those artifacts useful over time.

In short:

- raw sources remain immutable
- Synapse indexes both sources and notes
- an LLM-maintained markdown layer compiles durable synthesis from the sources
- Synapse retrieval remains the evidence substrate under that compiled layer

## Context

### What Karpathy Actually Proposed

The public "LLM Knowledge Bases" post and gist describe a workflow where an LLM incrementally compiles a persistent markdown wiki from raw sources, then answers questions and performs maintenance against that wiki instead of repeatedly rediscovering the same knowledge from scratch.

Primary references:

- X post summary: [LLM Knowledge Bases post by Andrej Karpathy](https://deepakness.com/raw/llm-knowledge-bases/)
- Public gist: [karpathy/llm-wiki.md](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)

Important details from the gist:

- the system has three layers: raw sources, generated wiki, and a schema/instruction layer
- the wiki is a persistent artifact that compounds over time
- ingest, query, and lint are the main operations
- at modest scale, a manually maintained `index.md` can be enough
- as the corpus grows, proper search becomes desirable again

This matters because some secondary coverage framed the post as "bypass RAG entirely". That is an overread. The gist itself is more nuanced: for small and medium corpora, compiled markdown can reduce repeated synthesis work; for larger corpora, you still want retrieval tooling.

### Why This Matters For Synapse

Synapse already has most of the lower-level primitives needed for this pattern:

- source-first ingest via bundles and sources
- markdown note indexing with provenance-aware frontmatter extraction
- note and source segment search
- discovery and link validation
- reasoning hooks in Cipher

Today, Synapse is strongest as a semantic retrieval and discovery engine over markdown corpora. What it does not yet provide is a first-class compiled knowledge layer that turns source evidence into durable, queryable synthesis notes.

That is the gap this RFC addresses.

## Problem

Synapse currently offers:

- retrieval over notes and sources
- hidden-link discovery
- graph integrity checks
- source ingest for research bundles

But it does not yet offer:

- persistent source-derived summaries
- compiled concept or entity pages maintained over time
- durable filing of user analyses back into the corpus
- health checks aimed at the compiled knowledge layer, not only link integrity

Without that layer, Synapse remains excellent at finding evidence, but weaker at accumulating interpretation.

## Product Thesis

Synapse should evolve from:

- "semantic shadow infrastructure for markdown vaults"

toward:

- "semantic infrastructure for evidence-backed markdown knowledge systems"

The business value is not generic note-taking. The value is that Synapse can provide a more trustworthy and more useful knowledge workflow than pure chat, pure wiki, or pure RAG alone:

- more durable than chat because synthesis persists as markdown artifacts
- more scalable than a hand-maintained wiki because the LLM handles bookkeeping
- more grounded than a freeform agent because retrieval, provenance, and storage remain explicit
- more inspectable than opaque RAG because the compiled outputs are human-readable files

## Goals

- Add an optional compiled markdown layer above existing retrieval.
- Preserve Synapse's retrieval-first and evidence-oriented architecture.
- Keep source material immutable and distinct from generated knowledge artifacts.
- Make generated notes provenance-aware and auditable.
- Let outputs from ingest and Q&A become durable assets in the corpus.
- Introduce maintenance flows for contradictions, stale syntheses, orphan pages, and missing concepts.

## Non-Goals

- Replace vector retrieval with directory scanning or giant-context prompting.
- Make Obsidian a required dependency.
- Let the LLM mutate raw sources.
- Build a fully autonomous writer with no review controls.
- Turn Synapse into a general-purpose PKM app.

## Design Principles

- Retrieval remains the substrate.
- Compiled knowledge is additive, not substitutive.
- Markdown artifacts are the product surface.
- Provenance is mandatory for generated knowledge.
- Deterministic mechanics stay below reasoning.
- Human review should be possible at every write boundary.

## Proposed Model

### Four Logical Layers

1. Raw sources

- immutable documents and extracted artifacts
- examples: article markdown, paper text, repo snapshots, image references, datasets

2. Indexed evidence

- source and note segments embedded and indexed by Synapse
- used for search, discovery, explanation, and maintenance

3. Compiled knowledge notes

- markdown files generated and updated by an LLM under Synapse control
- examples: source summaries, concept pages, entity pages, comparisons, theses, query outputs

4. Schema and policy

- rules for note kinds, frontmatter, allowed writes, provenance fields, maintenance workflows, and review requirements

### Knowledge Note Kinds

The compiled layer should start with a small controlled taxonomy:

- `source_summary`
- `concept`
- `entity`
- `comparison`
- `synthesis`
- `query_output`
- `maintenance_report`

This is preferable to unconstrained wiki growth. Synapse should optimize for useful, inspectable artifacts instead of maximal page count.

### Provenance Requirements

Every generated note should carry frontmatter that makes its evidence base explicit.

Minimum fields:

- `note_kind`
- `generated_by`
- `generated_at`
- `bundle_ids`
- `source_ids`
- `origin_urls`
- `status`

Recommended additional fields:

- `confidence`
- `supersedes`
- `related_notes`
- `open_questions`

In later iterations, Synapse can store structured evidence references down to segment identifiers in metadata or sidecar artifacts.

## Managed Wiki Structure

The compiled layer should not be an unbounded pile of LLM-generated files. It needs a managed topology so that both humans and agents can predict where things live.

### Reserved Directory Layout

This RFC proposes a reserved subtree inside the vault or workspace:

```text
_compiled/
  index.md
  log.md
  sources/
  concepts/
  entities/
  syntheses/
  comparisons/
  queries/
  maintenance/
```

Rationale:

- keeps generated artifacts separate from raw or hand-authored notes
- makes write permissions easier to constrain
- gives agents a stable mental model
- prevents the compiled layer from polluting the rest of the vault

This should be configurable, but the default should be opinionated.

### Canonical Files

The compiled layer should have a few canonical files managed by Synapse:

- `index.md`
  - top-level navigational entry point
  - lists major note kinds and recent/high-value artifacts
- `log.md`
  - append-only operational history
  - records ingest, query filing, lint passes, and maintenance actions
- optionally `now.md` in later phases
  - compact snapshot of recent activity, active investigations, and stale areas

These files should be treated as first-class product artifacts, not incidental byproducts.

### Directory Semantics

Suggested semantics:

- `sources/`
  - one note per ingested source or source bundle summary
  - optimized for traceability and review
- `concepts/`
  - stable topic pages that aggregate evidence across many sources
- `entities/`
  - named people, organizations, tools, datasets, papers, products, places, or other concrete referents
- `syntheses/`
  - higher-order thesis pages, strategic views, or evolving domain summaries
- `comparisons/`
  - head-to-head analyses, tradeoff pages, benchmark summaries
- `queries/`
  - filed outputs from important investigations or user questions
- `maintenance/`
  - reports, contradiction audits, stale-page audits, orphan-page audits, repair proposals

This structure is intentionally closer to a managed research wiki than to a freeform personal notebook.

### Naming And Slugs

Synapse should generate stable slugs and avoid path churn.

Rules:

- use deterministic slugging for generated files
- avoid renaming files unless there is a strong reason
- prefer metadata changes and redirects over path churn
- keep note titles human-readable even when file names are normalized

Examples:

- `_compiled/sources/attention-is-all-you-need.md`
- `_compiled/concepts/contextual-retrieval.md`
- `_compiled/comparisons/perplexity-0-6b-vs-4b.md`

### Frontmatter Schema

Every compiled note should follow a strict schema.

Example:

```yaml
---
note_kind: concept
title: Contextual Retrieval
status: active
generated_by: synapse
generated_at: 2026-04-10T12:00:00Z
bundle_ids:
  - bundle-2026-04-10-arxiv-batch
source_ids:
  - source-001
  - source-004
origin_urls:
  - https://example.com/paper-a
  - https://example.com/paper-b
related_notes:
  - _compiled/concepts/hybrid-search.md
  - _compiled/comparisons/contextual-vs-naive-rag.md
confidence: medium
---
```

Later iterations can add structured evidence blocks or sidecar provenance maps.

### Ownership Model

The compiled subtree should be considered Synapse-managed.

That means:

- Synapse may create or update notes there
- humans may inspect and edit them, but manual edits are outside Synapse guarantees
- when a file is Synapse-managed, generated metadata should make that explicit

An optional stricter mode can later protect certain files from direct edits and require changes through Synapse operations only.

## UI And Control Plane

The compiled knowledge layer should ship with a UI, but that UI should be an operational control plane, not a general-purpose markdown editor.

### Why A UI Matters

Without a UI, the compiled layer remains an internal agent trick.

The UI is needed for:

- inspecting provenance and evidence quickly
- reviewing write proposals before apply
- understanding the corpus state at a glance
- navigating between raw sources, compiled notes, and maintenance findings
- making Synapse useful to operators who are not living inside a terminal

### What The UI Should Not Try To Be

The UI should not try to become:

- an Obsidian replacement
- a Notion clone
- a full PKM editor
- a chat-first shell hiding system state

Obsidian and normal editors can remain excellent companions. Synapse's UI should focus on the parts only Synapse can do well: retrieval-backed inspection, provenance, and maintenance workflows.

### UI Positioning

The UI should be described internally as:

- the control plane for compiled knowledge

not:

- the main authoring surface

This keeps the scope disciplined and aligned with business value.

### Core UI Objects

The first UI should expose four primary object types:

- raw sources
- compiled notes
- evidence references
- maintenance items

These should all be linkable and navigable from one another.

### MVP Screens

#### 1. Corpus Overview

Purpose:

- show overall corpus health and recent activity

Widgets:

- source counts
- compiled note counts by kind
- recent ingests
- recent filed queries
- stale pages count
- orphan pages count
- contradictions or review queue count

This screen answers: "What changed, and is the knowledge base healthy?"

#### 2. Source Detail

Purpose:

- inspect a raw source and everything derived from it

Contents:

- source metadata
- raw artifact links
- extracted summary or abstract
- linked compiled notes
- recent compile actions
- evidence snippets indexed from the source

This screen answers: "What did this source contribute?"

#### 3. Compiled Note Detail

Purpose:

- inspect a generated note as an evidence-backed artifact

Contents:

- rendered markdown
- frontmatter summary
- source and bundle provenance
- related compiled notes
- supporting evidence excerpts
- stale or review flags
- last update history

This screen answers: "Why should I trust this page, and what supports it?"

#### 4. Maintenance Queue

Purpose:

- triage quality issues in the compiled layer

Contents:

- stale syntheses
- orphan pages
- missing concept candidates
- weak provenance notes
- contradiction reports
- pending repair proposals

This screen answers: "What needs attention next?"

#### 5. Discovery And Candidate Pages

Purpose:

- surface high-value opportunities for new knowledge artifacts

Contents:

- hidden-link discoveries
- candidate concept pages
- candidate comparisons
- suggested synthesis updates

This screen answers: "What should be compiled next?"

### First Interaction Model

The initial UI interaction model should be review-centric:

- preview proposed note creation
- preview proposed note updates
- inspect evidence before accepting
- accept or reject with minimal friction

The first versions should avoid rich in-browser editing. If a user wants full editing, they can open the underlying markdown in their preferred editor.

### UI Actions

The MVP UI should support a small set of explicit actions:

- ingest source or bundle
- run compile
- run lint
- file a query result
- approve update
- reject update
- open underlying markdown

Each action should have visible consequences in the corpus and in the operational log.

### Technical Delivery

Synapse already has HTTP/OpenAPI infrastructure, so the lowest-risk path is:

- add compiled-knowledge endpoints to the existing API
- build a small web UI on top of that API
- keep server-side operations aligned with CLI and MCP capabilities

This avoids inventing a separate product surface too early.

### UI Principles

- show provenance by default
- make evidence inspection one click away
- privilege review over freeform editing
- expose system state clearly
- keep raw, compiled, and maintenance layers visibly distinct

## Product Packaging

The compiled layer and UI should be packaged as an opinionated mode of Synapse, not a separate unrelated product.

Possible framing:

- Synapse Core
  - indexing, search, discovery, validation, APIs
- Synapse Knowledge
  - compiled wiki structure, filing, maintenance, control-plane UI

This keeps the current engine story intact while giving a clear path to a more complete product.

## User Flows

### 1. Ingest And Compile

Flow:

1. User adds a new raw source or prepared bundle.
2. Synapse ingests and indexes the evidence.
3. A compile job asks the LLM to:
   - create or update the source summary
   - update relevant concept or entity pages
   - update a corpus index page
   - append a maintenance log entry
4. Synapse writes markdown outputs into a managed knowledge directory.
5. Synapse re-indexes those generated notes.

This is the direct Synapse adaptation of Karpathy's ingest loop.

### 2. Query And File

Flow:

1. User asks a question.
2. Synapse retrieves relevant knowledge notes and supporting evidence.
3. The LLM produces an answer grounded in those artifacts.
4. Optionally, Synapse files that answer back into the corpus as a `query_output` or promotes it into a richer `comparison` or `synthesis` note.

This turns valuable analyses into durable assets instead of disposable chat.

### 3. Lint And Heal

Flow:

1. Synapse scans the compiled layer for issues.
2. Retrieval gathers related evidence and affected notes.
3. Cipher proposes repairs or follow-up work.
4. Depending on policy, Synapse either:
   - writes a maintenance report only
   - proposes changes for review
   - applies constrained updates automatically

Initial lint targets:

- broken wikilinks
- orphan generated notes
- stale syntheses after new source ingest
- missing concept pages for high-frequency terms
- contradictory claims across compiled notes
- notes with weak or absent provenance

## Architecture Fit

### What We Reuse

Existing Synapse systems already provide the right seams:

- source ingest in `synapse/research_ingest.py`
- source, note, and note-source relations in `synapse/db.py`
- provenance extraction and note-source linking in `synapse/index.py`
- hybrid retrieval in `synapse/search.py`
- integrity checks in `synapse/validate.py`
- maintenance review patterns in `synapse/gardener.py`
- reasoning facade in `synapse/cipher_service.py`

The compiled layer should be implemented as a new service on top of those seams, not by rewriting them.

### What Must Be Added

New modules, conceptually:

- `synapse/knowledge_compile.py`
- `synapse/knowledge_lint.py`
- `synapse/knowledge_schema.py`

Likely new CLI or service operations:

- `synapse-compile`
- `synapse-query-file`
- `synapse-lint-knowledge`

Possible transport additions:

- MCP tool for compile
- MCP tool for lint knowledge
- HTTP endpoints mirroring the same operations

## Why Retrieval Still Matters

The strongest lesson from the broader discussion around Karpathy's post is that the compiled wiki is not a reason to discard retrieval.

For Synapse, retrieval remains essential because:

- generated notes can drift from evidence
- large corpora outgrow simple index-file navigation
- maintenance tasks require evidence lookup
- explanations should cite grounded support, not only prior syntheses

The right Synapse interpretation is:

- compile knowledge when it creates durable value
- retrieve evidence when you need precision, repair, or verification

This complements Synapse's existing value instead of fighting it.

## Product Boundaries

### What Synapse Should Be

- a retrieval-native compiler and maintainer of markdown knowledge artifacts
- an evidence-oriented substrate for human-and-LLM research workflows
- a bridge between raw corpora and durable synthesized knowledge

### What Synapse Should Not Be

- an Obsidian-only automation bundle
- a generic agent shell with weak storage semantics
- a system that treats generated summaries as sufficient evidence
- a toy "second brain" app with little grounding

## Risks

### 1. Summary Drift

Generated notes may become more confident and more wrong over time.

Mitigation:

- require provenance fields
- keep source retrieval easy
- mark stale notes after relevant ingest events
- add lint checks for unsupported claims

### 2. Knowledge Bloat

The wiki can grow into a noisy graveyard of low-value pages.

Mitigation:

- controlled note taxonomy
- promotion thresholds for new notes
- periodic orphan and redundancy checks
- explicit archival states

### 3. Over-Autonomy

If the LLM can edit everything freely, trust drops fast.

Mitigation:

- immutable raw layer
- managed output directories
- optional review gates
- narrow write templates in early iterations

### 4. Product Dilution

Synapse could lose focus and become "another notes tool".

Mitigation:

- keep the core pitch evidence-first
- build on existing retrieval strengths
- treat compiled knowledge as a layer, not the whole product

## Phased Plan

### Phase 1: Minimal Viable Compiled Layer

Deliver:

- managed generated-note directory
- reserved `_compiled/` topology with canonical subdirectories
- `source_summary` generation from ingested bundles
- provenance frontmatter
- re-index generated notes into Synapse
- basic corpus `index.md` and append-only `log.md`
- minimal UI with corpus overview, source detail, note detail, and maintenance queue

Success criteria:

- a user can ingest a source and receive durable markdown outputs tied to that source
- generated notes become searchable through existing Synapse search
- a user can inspect compiled notes and provenance without leaving the Synapse UI

### Phase 2: Knowledge-Aware Maintenance

Deliver:

- linting for stale syntheses, orphan pages, missing concept pages, and weak provenance
- maintenance reports as markdown artifacts
- reviewable repair proposals
- review/apply UI flows for maintenance actions

Success criteria:

- Synapse can identify and explain quality issues in the compiled layer
- users can accept or reject proposed repairs from the UI

### Phase 3: Query Filing

Deliver:

- optional filing of answers as `query_output`, `comparison`, or `synthesis`
- promotion workflow from ephemeral answer to durable note
- UI affordance to file an answer directly into the compiled layer

Success criteria:

- user investigations compound into a better corpus over time
- filed outputs are easy to review and navigate later

### Phase 4: Richer Knowledge Graph Semantics

Deliver:

- structured evidence references
- better concept/entity merge logic
- contradiction tracking and supersession chains
- richer graph and traceability views in the UI

Success criteria:

- Synapse can support larger and more contested knowledge domains without flattening everything into summaries

## Recommendation

Synapse should adopt the strongest part of the Karpathy pattern:

- the idea of a persistent, compounding markdown knowledge layer maintained by an LLM

But it should reject the weaker interpretation:

- that retrieval infrastructure becomes unnecessary

The best fit for Synapse is a retrieval-backed compiled knowledge system:

- raw sources stay immutable
- Synapse indexes evidence
- the LLM compiles and maintains knowledge notes
- Synapse keeps those notes grounded, searchable, and repairable

That is additive to Synapse's current business value and creates a clearer path from "semantic search engine" to "evidence-backed knowledge operating system".

## Open Questions

- Should generated notes live inside the main vault or under a reserved managed subtree such as `synapse/` or `_compiled/`?
- Which note kinds are valuable enough for the first release?
- Should compile actions be fully automatic on ingest, or default to dry-run plus review?
- How strict should provenance requirements be in phase 1?
- Should `index.md` remain a human-facing navigation artifact, an LLM-facing bootstrap artifact, or both?
- Should the UI ship in the first compiled-layer release, or be required for the feature to feel coherent?
- How much manual editing of Synapse-managed notes should be supported or discouraged?
