"""Tests for the bundle-ingest service facade."""

from pathlib import Path

from synapse.service_api import IngestBundleRequest, ingest_bundle_artifact


def test_ingest_bundle_artifact_uses_shared_runtime(monkeypatch, tmp_path):
    bundle_path = tmp_path / "prepared_source_bundle.json"
    bundle_path.write_text("{}", encoding="utf-8")

    calls = {}

    class FakeStore:
        conn = None

        def initialize(self):
            calls["initialized"] = True

        def close(self):
            calls["closed"] = True

    class FakeIngestor:
        def __init__(self, db, embedding_client):
            calls["db"] = db
            calls["embedding_client"] = embedding_client

        def ingest_bundle_file(self, path: Path):
            calls["bundle_path"] = path

            class Result:
                bundle_id = "bundle-123"
                bundle_path = str(path)
                replaced_existing = True
                source_count = 2
                segment_count = 7

            return Result()

    monkeypatch.setattr("synapse.service_api.create_vector_store", lambda settings, db_path=None, embedding_dim=None: FakeStore())
    monkeypatch.setattr("synapse.service_api.ResearchBundleIngestor", FakeIngestor)
    monkeypatch.setattr("synapse.service_api.EmbeddingClient.from_provider", lambda provider: "embedder")

    response = ingest_bundle_artifact(
        IngestBundleRequest(
            bundle_path=str(bundle_path),
            db_path=str(tmp_path / "synapse.sqlite"),
        )
    )

    assert response.bundle_id == "bundle-123"
    assert response.replaced_existing is True
    assert response.segment_count == 7
    assert calls["initialized"] is True
    assert calls["closed"] is True
    assert calls["bundle_path"] == bundle_path
