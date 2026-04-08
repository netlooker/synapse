"""Tests for source-first research bundle ingestion."""

import json

from synapse.db import Database
from synapse.research_ingest import ResearchBundleIngestor


class FakeEmbedder:
    def embed(self, _text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]

    def embed_query(self, _query: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]

    def embed_document_chunks(
        self,
        chunks: list[str],
        document_title: str | None = None,
        document_path: str | None = None,
    ) -> list[list[float]]:
        return [[float(index + 1), 0.0, 0.0, 0.0] for index, _ in enumerate(chunks)]


def test_database_initializes_source_first_tables(tmp_path):
    db = Database(tmp_path / "synapse.sqlite", embedding_dim=4)
    db.initialize()
    try:
        tables = set(db.list_tables())
    finally:
        db.close()

    assert "bundles" in tables
    assert "sources" in tables
    assert "notes" in tables
    assert "note_sources" in tables
    assert "segments" in tables
    assert "segments_fts" in tables


def test_ingest_bundle_persists_bundle_sources_and_segments(tmp_path):
    db = Database(tmp_path / "synapse.sqlite", embedding_dim=4)
    db.initialize()
    try:
        bundle_path = tmp_path / "prepared_source_bundle.json"
        sidecar_path = tmp_path / "source_01.txt"
        sidecar_path.write_text(
            "Full text paragraph one.\n\nFull text paragraph two with provenance.",
            encoding="utf-8",
        )
        bundle_path.write_text(json.dumps({
            "bundle_id": "bundle-001",
            "workspace": "nyx",
            "sources": [
                {
                    "source_id": "source-01",
                    "origin_url": "https://example.com/origin",
                    "direct_paper_url": "https://example.com/paper.pdf",
                    "title": "Prepared Source",
                    "authors": [{"name": "Ada Lovelace"}, {"name": "Grace Hopper"}],
                    "published": "2026-04-08",
                    "source_type": "paper",
                    "retrieved_at": "2026-04-08T10:00:00Z",
                    "extraction_status": "complete",
                    "extraction_method": "prepared_bundle",
                    "summary": "Short summary of the source.",
                    "abstract": "Abstract paragraph one.\n\nAbstract paragraph two.",
                    "full_text_path": sidecar_path.name,
                    "json_path": "source_01.json",
                    "note_path": "notes/source-01.md",
                }
            ],
        }), encoding="utf-8")

        result = ResearchBundleIngestor(db=db, embedding_client=FakeEmbedder()).ingest_bundle_file(bundle_path)

        bundle = db.get_bundle("bundle-001")
        source = db.get_source("bundle-001", "source-01")
        assert result.bundle_id == "bundle-001"
        assert result.source_count == 1
        assert result.segment_count >= 3
        assert bundle is not None
        assert source is not None
        assert source["title"] == "Prepared Source"
        assert source["authors"] == ["Ada Lovelace", "Grace Hopper"]
        assert "Full text paragraph one." in source["full_text"]
        assert source["metadata"]["json_mirror_path"] == "source_01.json"

        segments = db.get_source_segments(source["id"])
        roles = [segment["content_role"] for segment in segments]
        assert "summary" in roles
        assert "abstract" in roles
        assert "full_text" in roles

        fts_rows = db.conn.execute("SELECT COUNT(*) FROM segments_fts").fetchone()[0]
        vec_rows = db.conn.execute("SELECT COUNT(*) FROM vec_segments").fetchone()[0]
        assert fts_rows == len(segments)
        assert vec_rows == len(segments)
    finally:
        db.close()


def test_reingest_replaces_existing_bundle_rows(tmp_path):
    db = Database(tmp_path / "synapse.sqlite", embedding_dim=4)
    db.initialize()
    try:
        bundle_path = tmp_path / "prepared_source_bundle.json"
        bundle_path.write_text(json.dumps({
            "bundle_id": "bundle-002",
            "sources": [
                {
                    "source_id": "source-01",
                    "title": "Original Title",
                    "summary": "Original summary.",
                }
            ],
        }), encoding="utf-8")

        ingestor = ResearchBundleIngestor(db=db, embedding_client=FakeEmbedder())
        first = ingestor.ingest_bundle_file(bundle_path)

        bundle_path.write_text(json.dumps({
            "bundle_id": "bundle-002",
            "sources": [
                {
                    "source_id": "source-01",
                    "title": "Updated Title",
                    "summary": "Updated summary.",
                }
            ],
        }), encoding="utf-8")
        second = ingestor.ingest_bundle_file(bundle_path)

        source = db.get_source("bundle-002", "source-01")
        bundle_count = db.conn.execute("SELECT COUNT(*) FROM bundles WHERE bundle_id = 'bundle-002'").fetchone()[0]
        source_count = db.conn.execute("""
            SELECT COUNT(*)
            FROM sources s
            JOIN bundles b ON b.id = s.bundle_row_id
            WHERE b.bundle_id = 'bundle-002'
        """).fetchone()[0]
        segment_count = db.conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        fts_count = db.conn.execute("SELECT COUNT(*) FROM segments_fts").fetchone()[0]

        assert first.replaced_existing is False
        assert second.replaced_existing is True
        assert bundle_count == 1
        assert source_count == 1
        assert segment_count == 1
        assert fts_count == 1
        assert source is not None
        assert source["title"] == "Updated Title"
        assert source["summary_text"] == "Updated summary."
    finally:
        db.close()
