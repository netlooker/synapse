"""Tests for synapse.search."""

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

    def search_similar(self, query_embedding, limit=10, scope="chunk", include_paths=None):
        include_paths = tuple(include_paths) if include_paths else None
        self.calls.append((tuple(query_embedding), limit, scope, include_paths))
        if scope == "note":
            return [
                {
                    "path": "vault/a.md",
                    "title": "Agency Memory",
                    "similarity": 0.61,
                    "chunk_text": "Document summary for Agency Memory",
                },
                {
                    "path": "vault/b.md",
                    "title": "Weak Signals",
                    "similarity": 0.52,
                    "chunk_text": "Document summary for Weak Signals",
                },
            ]
        if include_paths:
            return [
                {
                    "path": "vault/a.md",
                    "title": "Agency Memory",
                    "similarity": 0.77,
                    "chunk_text": "Focused chunk from Agency Memory",
                }
            ]
        return [
            {
                "path": "vault/c.md",
                "title": "Cybernetic Librarian",
                "similarity": 0.68,
                "chunk_text": "Focused chunk from Cybernetic Librarian",
            },
        ]


def test_hybrid_search_merges_note_and_chunk_results():
    db = FakeDB()
    searcher = Searcher(
        db=db,
        note_embedding_client=FakeEmbedder([0.1, 0.2]),
        chunk_embedding_client=FakeEmbedder([0.3, 0.4]),
        search_settings=SearchSettings(candidate_multiplier=3, note_weight=0.35, chunk_weight=0.65),
    )

    results = searcher.search("hidden links", limit=3, mode="hybrid")

    assert [row["path"] for row in results] == ["vault/a.md", "vault/c.md", "vault/b.md"]
    assert results[0]["snippet"] == "Focused chunk from Agency Memory"
    assert results[0]["chunk_similarity"] == 0.77
    assert results[0]["note_similarity"] == 0.61
    assert ("note" in [call[2] for call in db.calls]) and ("chunk" in [call[2] for call in db.calls])
    assert db.calls[1][3] == ("vault/a.md", "vault/b.md")
    assert db.calls[2][3] is None


def test_note_search_targets_note_scope_only():
    db = FakeDB()
    searcher = Searcher(
        db=db,
        note_embedding_client=FakeEmbedder([0.1, 0.2]),
        chunk_embedding_client=FakeEmbedder([0.3, 0.4]),
    )

    results = searcher.search("hidden links", limit=2, mode="note")

    assert [row["path"] for row in results] == ["vault/a.md", "vault/b.md"]
    assert all(call[2] == "note" for call in db.calls)


def test_hybrid_search_uses_filtered_chunks_before_fallback():
    db = FakeDB()
    searcher = Searcher(
        db=db,
        note_embedding_client=FakeEmbedder([0.1, 0.2]),
        chunk_embedding_client=FakeEmbedder([0.3, 0.4]),
        search_settings=SearchSettings(candidate_multiplier=2, note_weight=0.5, chunk_weight=0.5),
    )

    results = searcher.search("hidden links", limit=2, mode="hybrid")

    assert results[0]["path"] == "vault/a.md"
    assert results[1]["path"] == "vault/c.md"
    assert db.calls[1][3] == ("vault/a.md", "vault/b.md")


def test_chunk_search_can_boost_metadata_matches():
    class MetadataDB(FakeDB):
        def search_similar(self, query_embedding, limit=10, scope="chunk", include_paths=None):
            self.calls.append((tuple(query_embedding), limit, scope, tuple(include_paths) if include_paths else None))
            return [
                {
                    "path": "vault/a.md",
                    "title": "Generic Note",
                    "similarity": 0.74,
                    "chunk_text": "A generally similar chunk",
                    "tags": ["notes"],
                    "wikilinks": [],
                },
                {
                    "path": "vault/b.md",
                    "title": "Vector Maintenance",
                    "similarity": 0.70,
                    "chunk_text": "Chunk about stale embeddings and reindexing",
                    "tags": ["embeddings", "maintenance"],
                    "wikilinks": ["Cipher"],
                },
            ]

    db = MetadataDB()
    searcher = Searcher(
        db=db,
        note_embedding_client=FakeEmbedder([0.1, 0.2]),
        chunk_embedding_client=FakeEmbedder([0.3, 0.4]),
    )

    results = searcher.search("maintenance embeddings", limit=2, mode="chunk")

    assert [row["path"] for row in results] == ["vault/b.md", "vault/a.md"]
    assert results[0]["similarity"] > 0.70
