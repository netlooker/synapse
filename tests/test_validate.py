"""Tests for validation module."""

import pytest

from synapse.db import Database
from synapse.validate import find_broken_links


class TestLinkValidation:
    @pytest.fixture
    def mock_db(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        db = Database(db_path, embedding_dim=4)
        db.initialize()

        note_a = db.insert_note(
            note_path="vault/entities/DocA.md",
            title="DocA",
            body_text="Links to [[DocB]].",
            content_hash="hash-a",
            metadata={"wikilinks": ["DocB"]},
            commit=False,
        )
        note_b = db.insert_note(
            note_path="vault/entities/DocB.md",
            title="DocB",
            body_text="Links to [[NonExistent]].",
            content_hash="hash-b",
            metadata={"wikilinks": ["NonExistent"]},
            commit=False,
        )
        db.insert_segment(
            owner_kind="note",
            owner_id=note_a,
            note_row_id=note_a,
            content_role="note_body",
            segment_index=0,
            text="Links to [[DocB]].",
            embedding=[0.1, 0.1, 0.1, 0.1],
            commit=False,
        )
        db.insert_segment(
            owner_kind="note",
            owner_id=note_b,
            note_row_id=note_b,
            content_role="note_body",
            segment_index=0,
            text="Links to [[NonExistent]].",
            embedding=[0.1, 0.1, 0.1, 0.1],
            commit=False,
        )
        db.conn.commit()
        return db

    def test_find_broken_links(self, mock_db):
        broken = find_broken_links(mock_db)

        assert len(broken) == 1
        assert broken[0].source_path == "vault/entities/DocB.md"
        assert broken[0].target_link == "NonExistent"

    def test_valid_links_ignored(self, mock_db):
        broken = find_broken_links(mock_db)
        targets = [item.target_link for item in broken]
        assert "DocB" not in targets
