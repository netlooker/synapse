"""Tests for validation module."""

import pytest
from synapse.validate import find_broken_links, BrokenLink
from synapse.db import Database
import sqlite3

class TestLinkValidation:
    """Test broken link detection."""

    @pytest.fixture
    def mock_db(self, tmp_path):
        """Create a DB with some valid documents."""
        db_path = tmp_path / "test.sqlite"
        db = Database(db_path)
        db.initialize()
        
        # Valid docs
        # DocA links to DocB (valid)
        # DocB links to NonExistent (broken)
        docs = [
            ("cortex/entities/DocA.md", "DocA", "Links to [[DocB]]."),
            ("cortex/entities/DocB.md", "DocB", "Links to [[NonExistent]]."),
        ]
        
        for path, title, content in docs:
            doc_id = db.upsert_document(path, content, title)
            # Insert content as a chunk so the validator can read it
            db.insert_chunk(doc_id, 0, content, [0.0]*768)
            
        db.conn.commit()
        return db

    def test_find_broken_links(self, mock_db):
        """Should identify links pointing to non-existent titles."""
        broken = find_broken_links(mock_db)
        
        assert len(broken) == 1
        assert broken[0].source_path == "cortex/entities/DocB.md"
        assert broken[0].target_link == "NonExistent"

    def test_valid_links_ignored(self, mock_db):
        """Valid links should not be reported."""
        broken = find_broken_links(mock_db)
        targets = [b.target_link for b in broken]
        assert "DocB" not in targets
