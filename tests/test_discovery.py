"""Tests for discovery module — find unlinked similar documents."""

import pytest
from pathlib import Path
from synapse.discovery import (
    extract_wikilinks,
    Discovery,
    find_discoveries,
    discover_for_document,
)
from synapse.db import Database as SynapseDB
import numpy as np


class TestExtractWikilinks:
    """Test wikilink parsing from markdown content."""

    def test_single_link(self):
        """Extract a single wikilink."""
        content = "This links to [[Python]] for reference."
        links = extract_wikilinks(content)
        assert links == {"Python"}

    def test_multiple_links(self):
        """Extract multiple wikilinks."""
        content = "See [[PARA]] and [[CODE Method]] for details."
        links = extract_wikilinks(content)
        assert links == {"PARA", "CODE Method"}

    def test_no_links(self):
        """Return empty set when no links."""
        content = "Just plain text, no links here."
        links = extract_wikilinks(content)
        assert links == set()

    def test_duplicate_links(self):
        """Deduplicate repeated links."""
        content = "[[Python]] is great. Did I mention [[Python]]?"
        links = extract_wikilinks(content)
        assert links == {"Python"}

    def test_nested_brackets_ignored(self):
        """Handle edge cases with brackets."""
        content = "Code: `arr[[0]]` and link [[Actual Link]]"
        links = extract_wikilinks(content)
        assert "Actual Link" in links

    def test_multiline(self):
        """Extract links across multiple lines."""
        content = """# Title
        
See [[First Link]] for context.

Also check [[Second Link]].
"""
        links = extract_wikilinks(content)
        assert links == {"First Link", "Second Link"}

    def test_link_with_heading(self):
        """Extract links with heading anchors."""
        content = "See [[Document#Section]] for details."
        links = extract_wikilinks(content)
        # Should extract base document name
        assert "Document" in links or "Document#Section" in links


class TestDiscoveryDataclass:
    """Test Discovery dataclass."""

    def test_discovery_creation(self):
        """Create a discovery instance."""
        d = Discovery(
            source_path="cortex/entities/Python.md",
            source_title="Python",
            target_path="cortex/entities/Elixir.md",
            target_title="Elixir",
            similarity=0.75
        )
        assert d.source_title == "Python"
        assert d.target_title == "Elixir"
        assert d.similarity == 0.75

    def test_discovery_repr(self):
        """Discovery has readable representation."""
        d = Discovery(
            source_path="a.md",
            source_title="A",
            target_path="b.md",
            target_title="B",
            similarity=0.82
        )
        repr_str = repr(d)
        assert "A" in repr_str
        assert "B" in repr_str


class TestDiscoverForDocument:
    """Test single-document discovery."""

    @pytest.fixture
    def mock_db(self, tmp_path):
        """Create a test database with sample documents."""
        db_path = tmp_path / "test.sqlite"
        db = SynapseDB(db_path)
        db.initialize()  # Must initialize before use
        
        # Create sample documents with embeddings
        # Doc A links to Doc B but not to Doc C
        def pad_emb(vec):
            return vec + [0.0] * (768 - len(vec))

        docs = [
            {
                "path": "cortex/entities/DocA.md",
                "title": "DocA",
                "content": "Document A links to [[DocB]] but not C.",
                "embedding": pad_emb([1.0, 0.0, 0.0])
            },
            {
                "path": "cortex/entities/DocB.md",
                "title": "DocB",
                "content": "Document B, linked from A.",
                "embedding": pad_emb([0.9, 0.1, 0.0])
            },
            {
                "path": "cortex/entities/DocC.md",
                "title": "DocC",
                "content": "Document C, not linked anywhere.",
                "embedding": pad_emb([0.95, 0.05, 0.0])
            },
            {
                "path": "cortex/entities/DocD.md",
                "title": "DocD",
                "content": "Document D, completely different.",
                "embedding": pad_emb([0.0, 0.0, 1.0])
            },
        ]
        
        for doc in docs:
            # Insert document and get doc_id
            doc_id = db.upsert_document(doc["path"], doc["content"], doc["title"])
            # Insert chunk with embedding
            db.insert_chunk(doc_id, 0, doc["content"], doc["embedding"])
        
        db.conn.commit()
        return db

    def test_discovers_unlinked_similar(self, mock_db):
        """Should discover DocC as similar but unlinked to DocA."""
        discoveries = discover_for_document(
            mock_db,
            doc_path="cortex/entities/DocA.md",
            top_k=5,
            threshold=0.5
        )
        
        # Should find DocC (similar, not linked)
        target_titles = [d.target_title for d in discoveries]
        assert "DocC" in target_titles

    def test_excludes_already_linked(self, mock_db):
        """Should NOT discover DocB since DocA links to it."""
        discoveries = discover_for_document(
            mock_db,
            doc_path="cortex/entities/DocA.md",
            top_k=5,
            threshold=0.5
        )
        
        target_titles = [d.target_title for d in discoveries]
        assert "DocB" not in target_titles

    def test_excludes_dissimilar(self, mock_db):
        """Should NOT discover DocD since it's not similar."""
        discoveries = discover_for_document(
            mock_db,
            doc_path="cortex/entities/DocA.md",
            top_k=5,
            threshold=0.5
        )
        
        target_titles = [d.target_title for d in discoveries]
        assert "DocD" not in target_titles

    def test_no_self_discovery(self, mock_db):
        """Should never suggest linking to self."""
        discoveries = discover_for_document(
            mock_db,
            doc_path="cortex/entities/DocA.md",
            top_k=10,
            threshold=0.0  # Very low threshold
        )
        
        target_paths = [d.target_path for d in discoveries]
        assert "cortex/entities/DocA.md" not in target_paths

    def test_respects_threshold(self, mock_db):
        """Should filter by similarity threshold."""
        # High threshold should return fewer results
        high_threshold = discover_for_document(
            mock_db,
            doc_path="cortex/entities/DocA.md",
            top_k=10,
            threshold=0.99
        )
        
        low_threshold = discover_for_document(
            mock_db,
            doc_path="cortex/entities/DocA.md",
            top_k=10,
            threshold=0.1
        )
        
        assert len(high_threshold) <= len(low_threshold)

    def test_metadata_and_graph_signals_raise_stronger_candidate(self, tmp_path):
        """Shared tags and shared neighbors should promote a candidate."""
        db_path = tmp_path / "test.sqlite"
        db = SynapseDB(db_path, embedding_dim=4)
        db.initialize()

        docs = [
            {
                "path": "vault/source.md",
                "title": "Source",
                "content": "Source note mentions [[Shared Hub]] and semantic memory.",
                "metadata": {
                    "tags": ["retrieval", "embeddings"],
                    "wikilinks": ["Shared Hub"],
                    "frontmatter": {"status": "Draft", "area": "memory"},
                },
                "embedding": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "path": "vault/strong.md",
                "title": "Strong Candidate",
                "content": "Strong note mentions [[Shared Hub]] and vector memory.",
                "metadata": {
                    "tags": ["retrieval", "embeddings"],
                    "wikilinks": ["Shared Hub"],
                    "frontmatter": {"status": "Draft", "area": "memory"},
                },
                "embedding": [0.98, 0.02, 0.0, 0.0],
            },
            {
                "path": "vault/weak.md",
                "title": "Weak Candidate",
                "content": "Weak note is semantically close but structurally disconnected.",
                "metadata": {
                    "tags": ["ops"],
                    "wikilinks": [],
                    "frontmatter": {"status": "Stable", "area": "ops"},
                },
                "embedding": [0.985, 0.015, 0.0, 0.0],
            },
        ]

        for doc in docs:
            doc_id = db.upsert_document(
                doc["path"],
                f"hash:{doc['path']}",
                doc["title"],
                metadata=doc["metadata"],
            )
            db.insert_chunk(doc_id, 0, doc["content"], doc["embedding"], scope="chunk")

        discoveries = discover_for_document(
            db,
            doc_path="vault/source.md",
            top_k=5,
            threshold=0.1,
        )

        assert discoveries[0].target_path == "vault/strong.md"
        assert discoveries[0].metadata_score > 0.0
        assert discoveries[0].graph_score > 0.0
        db.close()


class TestFindDiscoveries:
    """Test batch discovery across all documents."""

    @pytest.fixture
    def populated_db(self, tmp_path):
        """Create database with interconnected documents."""
        db_path = tmp_path / "test.sqlite"
        db = SynapseDB(db_path)
        db.initialize()  # Must initialize before use
        
        # Create a small knowledge graph
        def pad_emb(vec):
            return vec + [0.0] * (768 - len(vec))

        docs = [
            ("Python.md", "Python", "A programming language. See [[Elixir]].", pad_emb([1, 0, 0])),
            ("Elixir.md", "Elixir", "Functional language on BEAM.", pad_emb([0.8, 0.2, 0])),
            ("BEAM.md", "BEAM", "Erlang virtual machine.", pad_emb([0.7, 0.3, 0])),
            ("Rust.md", "Rust", "Systems programming.", pad_emb([0.1, 0.9, 0])),
            ("Go.md", "Go", "Simple systems language.", pad_emb([0.15, 0.85, 0])),
        ]
        
        for path, title, content, emb in docs:
            full_path = f"cortex/entities/{path}"
            doc_id = db.upsert_document(full_path, content, title)
            db.insert_chunk(doc_id, 0, content, emb)
        
        db.conn.commit()
        return db

    def test_finds_multiple_discoveries(self, populated_db):
        """Should find discoveries across the corpus."""
        discoveries = find_discoveries(
            populated_db,
            threshold=0.5,
            top_k=3
        )
        
        # Should find some discoveries (BEAM similar to Python/Elixir but not linked)
        assert len(discoveries) > 0

    def test_discoveries_sorted_by_similarity(self, populated_db):
        """Discoveries should be sorted by similarity descending."""
        discoveries = find_discoveries(
            populated_db,
            threshold=0.3,
            top_k=5
        )
        
        if len(discoveries) >= 2:
            for i in range(len(discoveries) - 1):
                assert discoveries[i].similarity >= discoveries[i + 1].similarity

    def test_no_duplicate_pairs(self, populated_db):
        """Should not report both A→B and B→A."""
        discoveries = find_discoveries(
            populated_db,
            threshold=0.3,
            top_k=10
        )
        
        pairs = set()
        for d in discoveries:
            pair = tuple(sorted([d.source_path, d.target_path]))
            assert pair not in pairs, f"Duplicate pair: {pair}"
            pairs.add(pair)
