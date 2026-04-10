import json
from pathlib import Path

import pytest

from synapse.export_openapi import export_openapi_spec


def test_export_openapi_spec_writes_expected_routes(tmp_path):
    destination = tmp_path / "openapi.json"

    written = export_openapi_spec(destination)

    assert written == destination
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["info"]["title"] == "Synapse API"
    assert "/search" in payload["paths"]
    assert "/ingest-bundle" in payload["paths"]
    assert "/knowledge/overview" in payload["paths"]
    assert "/ui/knowledge/bundles/{bundle_id}" in payload["paths"]
    assert "/ui/knowledge/operations" in payload["paths"]
    assert "/cipher/explain" in payload["paths"]


def test_tracked_openapi_export_is_valid_json():
    tracked = Path("docs/openapi.json")
    if not tracked.exists():
        pytest.skip("Tracked OpenAPI export has not been generated yet")

    payload = json.loads(tracked.read_text(encoding="utf-8"))
    assert payload["info"]["title"] == "Synapse API"
    assert "/health" in payload["paths"]
    assert "/knowledge/overview" in payload["paths"]
    assert "/ui/knowledge/bundles/{bundle_id}" in payload["paths"]
    assert "/ui/knowledge/operations" in payload["paths"]
