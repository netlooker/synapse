"""Tests for source-first search."""

from synapse.search import Searcher
from synapse.settings import SearchSettings


class FakeEmbedder:
    def __init__(self, query_vector):
        self.query_vector = query_vector

    def embed(self, _query):
        return self.query_vector

    def embed_query(self, _query):
        return self.query_vector


class FakeDB:
    def __init__(self):
        self.calls = []

    def search_segments_lexical(self, query, *, limit=10, filters=None):
        self.calls.append(("lexical", query, limit, dict(filters or {})))
        return [
            {
                "segment_id": 1,
                "owner_kind": "source",
                "content_role": "summary",
                "segment_text": "Prepared summary about weak signals across papers.",
                "source_row_id": 10,
                "bundle_id": "bundle-1",
                "source_id": "source-a",
                "source_title": "Weak Signals",
                "origin_url": "https://example.com/weak-signals",
                "direct_paper_url": "https://example.com/weak-signals.pdf",
                "note_row_id": None,
                "note_path": None,
                "note_title": None,
                "note_kind": None,
                "title": "Weak Signals",
                "bm25_score": 0.15,
                "vector_score": None,
                "distance": None,
            },
            {
                "segment_id": 2,
                "owner_kind": "source",
                "content_role": "full_text",
                "segment_text": "Full text paragraph about cybernetic librarians.",
                "source_row_id": 11,
                "bundle_id": "bundle-1",
                "source_id": "source-b",
                "source_title": "Cybernetic Librarian",
                "origin_url": "https://example.com/librarian",
                "direct_paper_url": None,
                "note_row_id": None,
                "note_path": None,
                "note_title": None,
                "note_kind": None,
                "title": "Cybernetic Librarian",
                "bm25_score": 0.25,
                "vector_score": None,
                "distance": None,
            },
        ]

    def search_segments_vector(self, query_embedding, *, limit=10, filters=None):
        self.calls.append(("vector", tuple(query_embedding), limit, dict(filters or {})))
        return [
            {
                "segment_id": 1,
                "owner_kind": "source",
                "content_role": "summary",
                "segment_text": "Prepared summary about weak signals across papers.",
                "source_row_id": 10,
                "bundle_id": "bundle-1",
                "source_id": "source-a",
                "source_title": "Weak Signals",
                "origin_url": "https://example.com/weak-signals",
                "direct_paper_url": "https://example.com/weak-signals.pdf",
                "note_row_id": None,
                "note_path": None,
                "note_title": None,
                "note_kind": None,
                "title": "Weak Signals",
                "bm25_score": None,
                "vector_score": 0.82,
                "distance": 0.22,
            },
            {
                "segment_id": 3,
                "owner_kind": "source",
                "content_role": "abstract",
                "segment_text": "Abstract describing agency memory and retrieval.",
                "source_row_id": 12,
                "bundle_id": "bundle-2",
                "source_id": "source-c",
                "source_title": "Agency Memory",
                "origin_url": "https://example.com/agency",
                "direct_paper_url": None,
                "note_row_id": None,
                "note_path": None,
                "note_title": None,
                "note_kind": None,
                "title": "Agency Memory",
                "bm25_score": None,
                "vector_score": 0.75,
                "distance": 0.33,
            },
        ]


def test_research_search_merges_lexical_and_vector_candidates():
    db = FakeDB()
    searcher = Searcher(
        db=db,
        embedding_client=FakeEmbedder([0.1, 0.2]),
        search_settings=SearchSettings(candidate_multiplier=3, note_weight=0.4, chunk_weight=0.6),
    )

    results = searcher.search("weak signals", limit=3, mode="research")

    assert [row["source_id"] for row in results] == ["source-a", "source-c", "source-b"]
    assert results[0]["result_kind"] == "source"
    assert results[0]["matched_content_role"] == "summary"
    assert "hybrid agreement" in results[0]["rank_reason"]
    assert db.calls[0][0] == "lexical"
    assert db.calls[1][0] == "vector"


def test_source_mode_filters_to_source_owned_segments():
    db = FakeDB()
    searcher = Searcher(
        db=db,
        embedding_client=FakeEmbedder([0.1, 0.2]),
    )

    _ = searcher.search("source search", limit=2, mode="source", filters={"bundle_id": "bundle-1"})

    assert db.calls[0][3]["owner_kind"] == "source"
    assert db.calls[0][3]["bundle_id"] == "bundle-1"
    assert db.calls[1][3]["owner_kind"] == "source"


def test_evidence_mode_returns_segment_level_matches():
    db = FakeDB()
    searcher = Searcher(
        db=db,
        embedding_client=FakeEmbedder([0.1, 0.2]),
    )

    results = searcher.search("agency", limit=2, mode="evidence")

    assert [row["result_kind"] for row in results] == ["evidence", "evidence"]
    assert results[0]["matched_segment_text"].startswith("Prepared summary")
    assert results[0]["combined_score"] >= results[1]["combined_score"]
