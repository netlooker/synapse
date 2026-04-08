"""Tests for discovery module — find unlinked similar notes."""

from pathlib import Path

import pytest

from synapse.db import Database
from synapse.discovery import Discovery, discover_for_document, extract_wikilinks, find_discoveries


class TestExtractWikilinks:
    def test_single_link(self):
        assert extract_wikilinks("This links to [[Python]] for reference.") == {"Python"}

    def test_multiple_links(self):
        assert extract_wikilinks("See [[PARA]] and [[CODE Method]] for details.") == {"PARA", "CODE Method"}

    def test_no_links(self):
        assert extract_wikilinks("Just plain text, no links here.") == set()

    def test_link_with_heading(self):
        assert extract_wikilinks("See [[Document#Section]] for details.") == {"Document"}


class TestDiscoveryDataclass:
    def test_discovery_creation(self):
        discovery = Discovery(
            source_path="vault/entities/Python.md",
            source_title="Python",
            target_path="vault/entities/Elixir.md",
            target_title="Elixir",
            similarity=0.75,
        )
        assert discovery.source_title == "Python"
        assert discovery.target_title == "Elixir"
        assert discovery.similarity == 0.75


class TestDiscoverForDocument:
    @pytest.fixture
    def mock_db(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        db = Database(db_path, embedding_dim=4)
        db.initialize()

        docs = [
            {
                "path": "vault/entities/DocA.md",
                "title": "DocA",
                "content": "Document A links to [[DocB]] but not C.",
                "metadata": {"wikilinks": ["DocB"], "tags": ["retrieval"], "frontmatter": {"status": "Draft"}},
                "embedding": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "path": "vault/entities/DocB.md",
                "title": "DocB",
                "content": "Document B, linked from A.",
                "metadata": {"wikilinks": [], "tags": ["retrieval"], "frontmatter": {"status": "Draft"}},
                "embedding": [0.9, 0.1, 0.0, 0.0],
            },
            {
                "path": "vault/entities/DocC.md",
                "title": "DocC",
                "content": "Document C, not linked anywhere.",
                "metadata": {"wikilinks": [], "tags": ["retrieval"], "frontmatter": {"status": "Draft"}},
                "embedding": [0.95, 0.05, 0.0, 0.0],
            },
            {
                "path": "vault/entities/DocD.md",
                "title": "DocD",
                "content": "Document D, completely different.",
                "metadata": {"wikilinks": [], "tags": ["ops"], "frontmatter": {"status": "Stable"}},
                "embedding": [0.0, 0.0, 1.0, 0.0],
            },
        ]

        for doc in docs:
            note_id = db.insert_note(
                note_path=doc["path"],
                title=doc["title"],
                body_text=doc["content"],
                content_hash=f"hash:{doc['title']}",
                metadata=doc["metadata"],
                commit=False,
            )
            db.insert_segment(
                owner_kind="note",
                owner_id=note_id,
                note_row_id=note_id,
                content_role="note_body",
                segment_index=0,
                text=doc["content"],
                embedding=doc["embedding"],
                commit=False,
            )
        db.conn.commit()
        return db

    def test_discovers_unlinked_similar(self, mock_db):
        discoveries = discover_for_document(mock_db, doc_path="vault/entities/DocA.md", top_k=5, threshold=0.5)
        assert "DocC" in [item.target_title for item in discoveries]

    def test_excludes_already_linked(self, mock_db):
        discoveries = discover_for_document(mock_db, doc_path="vault/entities/DocA.md", top_k=5, threshold=0.5)
        assert "DocB" not in [item.target_title for item in discoveries]

    def test_excludes_dissimilar(self, mock_db):
        discoveries = discover_for_document(mock_db, doc_path="vault/entities/DocA.md", top_k=5, threshold=0.5)
        assert "DocD" not in [item.target_title for item in discoveries]

    def test_metadata_and_graph_signals_raise_stronger_candidate(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        db = Database(db_path, embedding_dim=4)
        db.initialize()

        docs = [
            {
                "path": "vault/source.md",
                "title": "Source",
                "content": "Source note mentions [[Shared Hub]] and semantic memory.",
                "metadata": {"tags": ["retrieval", "embeddings"], "wikilinks": ["Shared Hub"], "frontmatter": {"status": "Draft", "area": "memory"}},
                "embedding": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "path": "vault/strong.md",
                "title": "Strong Candidate",
                "content": "Strong note mentions [[Shared Hub]] and vector memory.",
                "metadata": {"tags": ["retrieval", "embeddings"], "wikilinks": ["Shared Hub"], "frontmatter": {"status": "Draft", "area": "memory"}},
                "embedding": [0.98, 0.02, 0.0, 0.0],
            },
            {
                "path": "vault/weak.md",
                "title": "Weak Candidate",
                "content": "Weak note is semantically close but structurally disconnected.",
                "metadata": {"tags": ["ops"], "wikilinks": [], "frontmatter": {"status": "Stable", "area": "ops"}},
                "embedding": [0.985, 0.015, 0.0, 0.0],
            },
        ]

        for doc in docs:
            note_id = db.insert_note(
                note_path=doc["path"],
                title=doc["title"],
                body_text=doc["content"],
                content_hash=f"hash:{doc['title']}",
                metadata=doc["metadata"],
                commit=False,
            )
            db.insert_segment(
                owner_kind="note",
                owner_id=note_id,
                note_row_id=note_id,
                content_role="note_body",
                segment_index=0,
                text=doc["content"],
                embedding=doc["embedding"],
                commit=False,
            )
        db.conn.commit()

        discoveries = discover_for_document(db, doc_path="vault/source.md", top_k=2, threshold=0.1)

        assert discoveries[0].target_path == "vault/strong.md"
        assert discoveries[0].metadata_score > 0.0
        assert discoveries[0].graph_score > 0.0


class TestFindDiscoveries:
    def test_finds_multiple_discoveries(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        db = Database(db_path, embedding_dim=4)
        db.initialize()

        docs = [
            ("vault/a.md", "A", "Alpha", [1.0, 0.0, 0.0, 0.0]),
            ("vault/b.md", "B", "Beta", [0.95, 0.05, 0.0, 0.0]),
            ("vault/c.md", "C", "Gamma", [0.0, 1.0, 0.0, 0.0]),
        ]
        for path, title, body, embedding in docs:
            note_id = db.insert_note(
                note_path=path,
                title=title,
                body_text=body,
                content_hash=f"hash:{title}",
                metadata={},
                commit=False,
            )
            db.insert_segment(
                owner_kind="note",
                owner_id=note_id,
                note_row_id=note_id,
                content_role="note_body",
                segment_index=0,
                text=body,
                embedding=embedding,
                commit=False,
            )
        db.conn.commit()

        discoveries = find_discoveries(db, threshold=0.2, top_k=2, max_total=5)

        assert len(discoveries) > 0
        assert all(isinstance(item, Discovery) for item in discoveries)
