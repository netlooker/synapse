"""
Tests for synapse.db - Database setup and operations
"""
import sqlite3
import tempfile
from pathlib import Path

import pytest


class TestDatabaseSetup:
    """Test database initialization and schema creation."""

    def test_create_database_creates_file(self):
        """Database file should be created on init."""
        from synapse.db import Database
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path)
            db.initialize()
            
            assert db_path.exists()
            db.close()

    def test_tables_are_created(self):
        """All required tables should exist after init."""
        from synapse.db import Database
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path)
            db.initialize()
            
            # Check tables exist
            tables = db.list_tables()
            assert "documents" in tables
            assert "chunks" in tables
            assert "discoveries" in tables
            db.close()

    def test_sqlite_vec_extension_loaded(self):
        """sqlite-vec extension should be loaded and functional."""
        from synapse.db import Database
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path)
            db.initialize()
            
            # Verify vec0 is available
            version = db.vec_version()
            assert version is not None
            assert "v" in version  # e.g., "v0.1.6"
            db.close()


class TestDocumentOperations:
    """Test document CRUD operations."""

    def test_insert_document(self):
        """Should insert a document and return its ID."""
        from synapse.db import Database
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path)
            db.initialize()
            
            doc_id = db.upsert_document(
                path="vault/entities/Test.md",
                content_hash="abc123",
                title="Test Entity"
            )
            
            assert doc_id is not None
            assert doc_id > 0
            db.close()

    def test_get_document_by_path(self):
        """Should retrieve document by path."""
        from synapse.db import Database
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path)
            db.initialize()
            
            db.upsert_document(
                path="vault/entities/Test.md",
                content_hash="abc123",
                title="Test Entity"
            )
            
            doc = db.get_document("vault/entities/Test.md")
            assert doc is not None
            assert doc["title"] == "Test Entity"
            assert doc["content_hash"] == "abc123"
            db.close()

    def test_upsert_updates_existing(self):
        """Upsert should update hash if document exists."""
        from synapse.db import Database
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path)
            db.initialize()
            
            # Insert
            doc_id1 = db.upsert_document(
                path="vault/entities/Test.md",
                content_hash="abc123",
                title="Test Entity"
            )
            
            # Update
            doc_id2 = db.upsert_document(
                path="vault/entities/Test.md",
                content_hash="def456",
                title="Test Entity Updated"
            )
            
            assert doc_id1 == doc_id2  # Same document
            
            doc = db.get_document("vault/entities/Test.md")
            assert doc["content_hash"] == "def456"
            assert doc["title"] == "Test Entity Updated"
            db.close()


class TestChunkOperations:
    """Test chunk storage and vector search."""

    def test_insert_chunk_with_embedding(self):
        """Should insert a chunk with its embedding."""
        from synapse.db import Database
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path)
            db.initialize()
            
            doc_id = db.upsert_document(
                path="vault/entities/Test.md",
                content_hash="abc123",
                title="Test"
            )
            
            # Fake 768-dim embedding
            embedding = [0.1] * 768
            
            chunk_id = db.insert_chunk(
                doc_id=doc_id,
                chunk_index=0,
                chunk_text="This is test content.",
                embedding=embedding
            )
            
            assert chunk_id is not None
            assert chunk_id > 0
            db.close()

    def test_vector_search_returns_similar(self):
        """Vector search should return similar chunks."""
        from synapse.db import Database
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path)
            db.initialize()
            
            # Insert two documents with different embeddings
            doc1_id = db.upsert_document("doc1.md", "hash1", "Doc 1")
            doc2_id = db.upsert_document("doc2.md", "hash2", "Doc 2")
            
            # Similar embeddings (small difference)
            emb1 = [0.1] * 768
            emb2 = [0.1] * 767 + [0.2]  # Slightly different
            emb3 = [0.9] * 768  # Very different
            
            db.insert_chunk(doc1_id, 0, "Content about Elixir", emb1)
            db.insert_chunk(doc1_id, 1, "More Elixir content", emb2)
            db.insert_chunk(doc2_id, 0, "Unrelated content", emb3)
            
            # Search with emb1 - should find emb2 as similar
            results = db.search_similar(emb1, limit=2)
            
            assert len(results) >= 1
            assert all(0.0 <= row["similarity"] <= 1.0 for row in results)
            # First result should be exact match or very similar
            db.close()

    def test_delete_chunks_for_document(self):
        """Should delete all chunks when re-indexing a document."""
        from synapse.db import Database
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path)
            db.initialize()
            
            doc_id = db.upsert_document("test.md", "hash1", "Test")
            embedding = [0.1] * 768
            
            db.insert_chunk(doc_id, 0, "Chunk 1", embedding)
            db.insert_chunk(doc_id, 1, "Chunk 2", embedding)
            
            # Delete chunks for re-indexing
            deleted = db.delete_chunks(doc_id)
            assert deleted == 2
            
            # Verify chunks are gone
            chunks = db.get_chunks(doc_id)
            assert len(chunks) == 0
            db.close()

    def test_vector_search_can_filter_by_scope(self):
        """Search should be able to target note or chunk embeddings separately."""
        from synapse.db import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path, embedding_dim=4)
            db.initialize()

            doc_id = db.upsert_document("doc1.md", "hash1", "Doc 1")
            embedding = [0.1, 0.1, 0.1, 0.1]

            db.insert_chunk(doc_id, 0, "Document level summary", embedding, scope="note")
            db.insert_chunk(doc_id, 0, "Section chunk", embedding, scope="chunk")

            note_results = db.search_similar(embedding, limit=5, scope="note")
            chunk_results = db.search_similar(embedding, limit=5, scope="chunk")

            assert len(note_results) == 1
            assert len(chunk_results) == 1
            assert note_results[0]["chunk_text"] == "Document level summary"
            assert chunk_results[0]["chunk_text"] == "Section chunk"
            db.close()

    def test_vector_search_can_filter_by_candidate_paths(self):
        """Search should be able to constrain results to coarse retrieval candidates."""
        from synapse.db import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path, embedding_dim=4)
            db.initialize()

            doc1_id = db.upsert_document("vault/a.md", "hash1", "Doc A")
            doc2_id = db.upsert_document("vault/b.md", "hash2", "Doc B")
            embedding = [0.1, 0.1, 0.1, 0.1]

            db.insert_chunk(doc1_id, 0, "Candidate chunk", embedding, scope="chunk")
            db.insert_chunk(doc2_id, 0, "Excluded chunk", embedding, scope="chunk")

            results = db.search_similar(
                embedding,
                limit=5,
                scope="chunk",
                include_paths=["vault/b.md"],
            )

            assert len(results) == 1
            assert results[0]["path"] == "vault/b.md"
            db.close()


class TestSourceFirstSearchOperations:
    def test_segment_search_supports_lexical_and_vector_queries(self):
        from synapse.db import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db = Database(db_path, embedding_dim=4)
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
