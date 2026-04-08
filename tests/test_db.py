"""Tests for Synapse's source-first database layer."""

import tempfile
from pathlib import Path


class TestDatabaseSetup:
    def test_create_database_creates_file(self):
        from synapse.db import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path)
            db.initialize()

            assert db_path.exists()
            db.close()

    def test_tables_are_created(self):
        from synapse.db import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path)
            db.initialize()

            tables = set(db.list_tables())
            assert {
                "bundles",
                "sources",
                "notes",
                "note_sources",
                "segments",
                "vec_segments",
                "segments_fts",
                "discoveries",
            }.issubset(tables)
            assert "documents" not in tables
            assert "chunks" not in tables
            assert "vec_chunks" not in tables
            db.close()

    def test_sqlite_vec_extension_loaded(self):
        from synapse.db import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path)
            db.initialize()

            version = db.vec_version()
            assert version is not None
            assert "v" in version
            db.close()


class TestSourceCorpusOperations:
    def test_bundle_source_note_and_lineage_round_trip(self):
        from synapse.db import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "test.sqlite", embedding_dim=4)
            db.initialize()

            bundle_row_id = db.upsert_bundle(
                "bundle-1",
                "hash-1",
                artifact_path="/tmp/prepared_source_bundle.json",
                metadata={"workspace": "research"},
                artifact={"bundle_id": "bundle-1"},
                commit=False,
            )
            source_row_id = db.insert_source(
                bundle_row_id,
                "source-1",
                title="Weak Signals",
                origin_url="https://example.com/origin",
                direct_paper_url="https://example.com/paper.pdf",
                authors=["Ada Lovelace"],
                source_type="paper",
                summary_text="Weak signals summary",
                commit=False,
            )
            note_id = db.insert_note(
                note_path="notes/weak-signals.md",
                title="Weak Signals",
                body_text="# Weak Signals\n\nA linked research note.",
                note_kind="research",
                metadata={"bundle_id": "bundle-1", "source_id": "source-1"},
                commit=False,
            )
            db.link_note_source(note_id, source_row_id, metadata={"linked_via": "frontmatter"}, commit=False)
            db.conn.commit()

            bundle = db.get_bundle("bundle-1")
            source = db.get_source("bundle-1", "source-1")
            note = db.get_note("notes/weak-signals.md")
            link = db.conn.execute(
                "SELECT metadata_json FROM note_sources WHERE note_id = ? AND source_row_id = ?",
                (note_id, source_row_id),
            ).fetchone()

            assert bundle is not None
            assert bundle["artifact_path"] == "/tmp/prepared_source_bundle.json"
            assert source is not None
            assert source["title"] == "Weak Signals"
            assert source["authors"] == ["Ada Lovelace"]
            assert note is not None
            assert note["metadata"]["bundle_id"] == "bundle-1"
            assert link is not None
            db.close()

    def test_segment_search_supports_lexical_and_vector_queries(self):
        from synapse.db import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "test.sqlite", embedding_dim=4)
            db.initialize()

            bundle_row_id = db.upsert_bundle("bundle-1", "hash-1", commit=False)
            source_row_id = db.insert_source(
                bundle_row_id,
                "source-1",
                title="Weak Signals",
                summary_text="Weak signals summary",
                source_type="paper",
                commit=False,
            )
            db.insert_segment(
                owner_kind="source",
                owner_id=source_row_id,
                source_row_id=source_row_id,
                content_role="summary",
                segment_index=0,
                text="Weak signals summary for retrieval systems.",
                embedding=[0.1, 0.1, 0.1, 0.1],
                commit=False,
            )
            db.conn.commit()

            lexical = db.search_segments_lexical(
                "weak signals",
                limit=5,
                filters={"bundle_id": "bundle-1", "owner_kind": "source"},
            )
            vector = db.search_segments_vector(
                [0.1, 0.1, 0.1, 0.1],
                limit=5,
                filters={"source_id": "source-1"},
            )

            assert len(lexical) == 1
            assert lexical[0]["source_id"] == "source-1"
            assert lexical[0]["title"] == "Weak Signals"
            assert len(vector) == 1
            assert vector[0]["vector_score"] is not None
            db.close()

    def test_delete_note_removes_segments(self):
        from synapse.db import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "test.sqlite", embedding_dim=4)
            db.initialize()

            note_id = db.insert_note(
                note_path="notes/test.md",
                title="Test",
                body_text="Body",
                commit=False,
            )
            db.insert_segment(
                owner_kind="note",
                owner_id=note_id,
                note_row_id=note_id,
                content_role="note_body",
                segment_index=0,
                text="Body",
                embedding=[0.2, 0.2, 0.2, 0.2],
                commit=False,
            )
            db.conn.commit()

            deleted = db.delete_note(note_id)
            remaining = db.conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]

            assert deleted == 1
            assert remaining == 0
            db.close()

    def test_delete_bundle_removes_source_segments(self):
        from synapse.db import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "test.sqlite", embedding_dim=4)
            db.initialize()

            bundle_row_id = db.upsert_bundle("bundle-1", "hash-1", commit=False)
            source_row_id = db.insert_source(bundle_row_id, "source-1", title="Source", commit=False)
            db.insert_segment(
                owner_kind="source",
                owner_id=source_row_id,
                source_row_id=source_row_id,
                content_role="full_text",
                segment_index=0,
                text="Primary text",
                embedding=[0.3, 0.3, 0.3, 0.3],
                commit=False,
            )
            db.conn.commit()

            deleted = db.delete_bundle("bundle-1")
            remaining_sources = db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            remaining_segments = db.conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]

            assert deleted == 1
            assert remaining_sources == 0
            assert remaining_segments == 0
            db.close()
