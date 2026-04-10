"""End-to-end tests for the compiled knowledge layer (Phase 1)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from synapse.db import Database
from synapse.errors import (
    SynapseBadRequestError,
    SynapseConflictError,
    SynapseNotFoundError,
)
from synapse.index import Indexer
from synapse.knowledge_schema import (
    KnowledgeNoteKind,
    managed_index_path,
    managed_log_path,
    managed_note_path,
)
from synapse.knowledge_service import KnowledgeService
from synapse.research_ingest import ResearchBundleIngestor
from synapse.search import Searcher
from synapse.settings import AppSettings, KnowledgeSettings, SearchSettings


class FakeEmbedder:
    """Dependency-free embedder mirroring the one used in ingest tests."""

    def embed(self, _text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]

    def embed_query(self, _query: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    def embed_document_chunks(
        self,
        chunks: list[str],
        document_title: str | None = None,
        document_path: str | None = None,
    ) -> list[list[float]]:
        return [[float(i + 1), 0.0, 0.0, 0.0] for i, _ in enumerate(chunks)]


class ExplodingIndexer:
    def __init__(self, fail_on_call: int = 1):
        self.fail_on_call = fail_on_call
        self.calls = 0

    def index_file(self, path: Path):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError(f"boom: {path}")
        return {"path": path.as_posix()}


@pytest.fixture()
def knowledge_env(tmp_path):
    """Build a real on-disk vault + DB with an ingested source bundle."""
    vault = tmp_path / "vault"
    vault.mkdir()
    db_path = tmp_path / "synapse.sqlite"

    db = Database(db_path, embedding_dim=4)
    db.initialize()

    sidecar = tmp_path / "source_01.txt"
    sidecar.write_text(
        "The Transformer architecture relies entirely on self-attention.\n\n"
        "This paragraph also mentions attention heads and positional encodings.",
        encoding="utf-8",
    )
    bundle_path = tmp_path / "prepared_source_bundle.json"
    bundle_path.write_text(
        json.dumps(
            {
                "bundle_id": "bundle-001",
                "workspace": "nyx",
                "sources": [
                    {
                        "source_id": "source-attention",
                        "origin_url": "https://arxiv.org/abs/1706.03762",
                        "direct_paper_url": "https://arxiv.org/pdf/1706.03762",
                        "title": "Attention Is All You Need",
                        "authors": [{"name": "Vaswani"}, {"name": "Shazeer"}],
                        "published": "2017-06-12",
                        "source_type": "paper",
                        "retrieved_at": "2026-04-08T10:00:00Z",
                        "extraction_status": "complete",
                        "extraction_method": "prepared_bundle",
                        "summary": "The Transformer: attention-only sequence transduction.",
                        "abstract": "We propose the Transformer, based solely on attention.",
                        "full_text_path": sidecar.name,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    ResearchBundleIngestor(db=db, embedding_client=FakeEmbedder()).ingest_bundle_file(bundle_path)

    settings = AppSettings(
        knowledge=KnowledgeSettings(enabled=True, managed_root="_knowledge"),
        search=SearchSettings(
            provider="default",
            limit=5,
            candidate_multiplier=4,
            note_weight=0.5,
            chunk_weight=0.5,
        ),
    )

    def indexer_factory() -> Indexer:
        return Indexer(
            db=db,
            vault_root=vault,
            note_embedding_client=FakeEmbedder(),
            chunk_embedding_client=FakeEmbedder(),
            min_chunk_chars=200,
            max_chunk_chars=800,
            target_chunk_tokens=120,
            max_chunk_tokens=200,
            chunk_overlap_chars=40,
            chunk_strategy="hybrid",
            include_patterns=("**/*.md",),
            exclude_patterns=(),
        )

    service = KnowledgeService(
        store=db,
        settings=settings,
        vault_root=vault,
        indexer_factory=indexer_factory,
    )

    try:
        yield {
            "db": db,
            "vault": vault,
            "settings": settings,
            "service": service,
            "indexer_factory": indexer_factory,
        }
    finally:
        db.close()


def test_compile_bundle_creates_source_summary_proposals(knowledge_env):
    service: KnowledgeService = knowledge_env["service"]
    result = service.compile_bundle("bundle-001")

    assert result.bundle_id == "bundle-001"
    assert result.created_count == 1
    assert len(result.proposal_ids) == 1

    proposal = service.get_proposal(result.proposal_ids[0])
    assert proposal["note_kind"] == "source_summary"
    assert proposal["status"] == "pending"
    assert proposal["title"] == "Attention Is All You Need"
    assert proposal["target_path"] == managed_note_path(
        "_knowledge",
        KnowledgeNoteKind.SOURCE_SUMMARY,
        "source-attention",
        "bundle-001",
    )
    # Frontmatter round-trips through JSON storage.
    fm = proposal["frontmatter"]
    assert fm["note_kind"] == "source_summary"
    assert fm["bundle_ids"] == ["bundle-001"]
    assert fm["source_ids"] == ["source-attention"]
    # Body contains provenance + summary + abstract sections.
    body = proposal["body_markdown"]
    assert "## Provenance" in body
    assert "- bundle: `bundle-001`" in body
    assert "## Summary" in body
    assert "## Abstract" in body


def test_compile_bundle_missing_raises_not_found(knowledge_env):
    service: KnowledgeService = knowledge_env["service"]
    with pytest.raises(SynapseNotFoundError):
        service.compile_bundle("bundle-missing")


def test_apply_proposal_writes_note_updates_index_log_and_reindexes(knowledge_env):
    service: KnowledgeService = knowledge_env["service"]
    vault: Path = knowledge_env["vault"]

    compile_result = service.compile_bundle("bundle-001")
    proposal_id = compile_result.proposal_ids[0]

    apply_result = service.apply_proposal(proposal_id)

    # File written to the managed subtree.
    written_path = Path(apply_result.written_path)
    assert written_path.exists()
    contents = written_path.read_text(encoding="utf-8")
    assert contents.startswith("---\n")
    assert "note_kind: source_summary" in contents
    assert "Attention Is All You Need" in contents

    # Proposal is now applied.
    after = service.get_proposal(proposal_id)
    assert after["status"] == "applied"
    assert after["reviewer_action"]["action"] == "apply"

    # index.md and log.md are present under the managed root.
    index_path = vault / managed_index_path("_knowledge")
    log_path = vault / managed_log_path("_knowledge")
    assert index_path.exists()
    assert log_path.exists()
    index_body = index_path.read_text(encoding="utf-8")
    assert "source_summary" in index_body
    assert "Attention Is All You Need" in index_body
    assert "(sources/bundle-001/source-attention.md)" in index_body
    log_body = log_path.read_text(encoding="utf-8")
    assert f"apply :: proposal #{proposal_id}" in log_body

    # Reindex touched the compiled note plus index/log.
    reindexed_rels = set(apply_result.reindexed_files)
    assert any("sources/bundle-001/source-attention.md" in rel for rel in reindexed_rels)
    assert any(rel.endswith("index.md") for rel in reindexed_rels)
    assert any(rel.endswith("log.md") for rel in reindexed_rels)


def test_search_returns_compiled_note_after_apply(knowledge_env):
    service: KnowledgeService = knowledge_env["service"]
    db: Database = knowledge_env["db"]
    settings: AppSettings = knowledge_env["settings"]

    compile_result = service.compile_bundle("bundle-001")
    service.apply_proposal(compile_result.proposal_ids[0])

    searcher = Searcher(
        db=db,
        embedding_client=FakeEmbedder(),
        search_settings=settings.search,
    )
    results = searcher.search("Transformer attention", limit=10, mode="note")

    compiled_rel = managed_note_path(
        "_knowledge",
        KnowledgeNoteKind.SOURCE_SUMMARY,
        "source-attention",
        "bundle-001",
    )
    note_paths = [row.get("note_path") for row in results]
    assert compiled_rel in note_paths, note_paths


def test_apply_proposal_is_idempotent_guard(knowledge_env):
    service: KnowledgeService = knowledge_env["service"]
    proposal_id = service.compile_bundle("bundle-001").proposal_ids[0]
    service.apply_proposal(proposal_id)

    with pytest.raises(SynapseBadRequestError):
        service.apply_proposal(proposal_id)


def test_apply_proposal_detects_on_disk_conflict(knowledge_env):
    service: KnowledgeService = knowledge_env["service"]
    vault: Path = knowledge_env["vault"]
    proposal_id = service.compile_bundle("bundle-001").proposal_ids[0]

    proposal = service.get_proposal(proposal_id)
    target = vault / proposal["target_path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# hand-edited\n\nsomething else\n", encoding="utf-8")

    with pytest.raises(SynapseConflictError):
        service.apply_proposal(proposal_id)


def test_apply_proposal_rolls_back_when_reindex_fails(knowledge_env):
    env = knowledge_env
    proposal_id = env["service"].compile_bundle("bundle-001").proposal_ids[0]
    exploding = ExplodingIndexer(fail_on_call=1)
    rollback_service = KnowledgeService(
        store=env["db"],
        settings=env["settings"],
        vault_root=env["vault"],
        indexer_factory=lambda: exploding,
    )

    with pytest.raises(RuntimeError, match="boom"):
        rollback_service.apply_proposal(proposal_id)

    proposal = rollback_service.get_proposal(proposal_id)
    assert proposal["status"] == "pending"
    assert not (env["vault"] / proposal["target_path"]).exists()
    assert not (env["vault"] / managed_index_path("_knowledge")).exists()
    assert not (env["vault"] / managed_log_path("_knowledge")).exists()


def test_reject_proposal_marks_status_and_logs(knowledge_env):
    service: KnowledgeService = knowledge_env["service"]
    vault: Path = knowledge_env["vault"]
    proposal_id = service.compile_bundle("bundle-001").proposal_ids[0]

    refreshed = service.reject_proposal(proposal_id, reason="not relevant")
    assert refreshed["status"] == "rejected"
    assert refreshed["reviewer_action"]["action"] == "reject"
    assert refreshed["reviewer_action"]["reason"] == "not relevant"

    log_body = (vault / managed_log_path("_knowledge")).read_text(encoding="utf-8")
    assert f"reject :: proposal #{proposal_id}" in log_body
    assert "not relevant" in log_body

    with pytest.raises(SynapseBadRequestError):
        service.apply_proposal(proposal_id)


def test_overview_reports_counts_and_recent_proposals(knowledge_env):
    service: KnowledgeService = knowledge_env["service"]
    service.compile_bundle("bundle-001")

    overview = service.overview()
    assert overview["managed_root"] == "_knowledge"
    assert overview["counts"].get("pending") == 1
    assert len(overview["recent_proposals"]) == 1
    assert overview["recent_proposals"][0]["note_kind"] == "source_summary"


def test_source_summary_paths_are_scoped_by_bundle(knowledge_env, tmp_path):
    db: Database = knowledge_env["db"]
    settings: AppSettings = knowledge_env["settings"]
    vault: Path = knowledge_env["vault"]

    second_bundle = tmp_path / "prepared_source_bundle_2.json"
    second_bundle.write_text(
        json.dumps(
            {
                "bundle_id": "bundle-002",
                "sources": [
                    {
                        "source_id": "source-attention",
                        "origin_url": "https://example.com/other",
                        "title": "Another Attention Source",
                        "summary": "Another source with the same source_id.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    ResearchBundleIngestor(db=db, embedding_client=FakeEmbedder()).ingest_bundle_file(second_bundle)

    service = KnowledgeService(
        store=db,
        settings=settings,
        vault_root=vault,
        indexer_factory=knowledge_env["indexer_factory"],
    )
    first = service.compile_bundle("bundle-001")
    second = service.compile_bundle("bundle-002")

    first_path = service.get_proposal(first.proposal_ids[0])["target_path"]
    second_path = service.get_proposal(second.proposal_ids[0])["target_path"]

    assert first_path == "_knowledge/sources/bundle-001/source-attention.md"
    assert second_path == "_knowledge/sources/bundle-002/source-attention.md"
    assert first_path != second_path


def test_service_disabled_feature_gate(knowledge_env):
    env = knowledge_env
    disabled_settings = replace(
        env["settings"], knowledge=KnowledgeSettings(enabled=False)
    )
    gated = KnowledgeService(
        store=env["db"],
        settings=disabled_settings,
        vault_root=env["vault"],
        indexer_factory=env["indexer_factory"],
    )
    with pytest.raises(SynapseBadRequestError):
        gated.compile_bundle("bundle-001")
    with pytest.raises(SynapseBadRequestError):
        gated.overview()
