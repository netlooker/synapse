import json
from pathlib import Path

import pytest

from synapse.export_openapi import export_openapi_spec
from synapse.web_api import _SYNAPSE_VERSION


def test_export_openapi_spec_writes_expected_routes(tmp_path):
    destination = tmp_path / "openapi.json"

    written = export_openapi_spec(destination)

    assert written == destination
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["info"]["title"] == "Synapse API"
    assert payload["info"]["version"] == _SYNAPSE_VERSION
    assert "/search" in payload["paths"]
    assert "/ingest-bundle" in payload["paths"]
    assert "/knowledge/overview" in payload["paths"]
    assert "/ui/knowledge/bundles/{bundle_id}" in payload["paths"]
    assert "/ui/knowledge/operations" in payload["paths"]
    assert "/cipher/explain" in payload["paths"]


def test_tracked_openapi_export_matches_current_package_version():
    """The committed spec must track the pyproject version.

    Re-run ``synapse-export-openapi`` whenever you bump the version in
    ``pyproject.toml``. This test guards against the silent drift we hit
    between 0.1.0 and 0.3.0 where the OpenAPI spec kept reporting 0.1.0.
    """
    tracked = Path("docs/openapi.json")
    if not tracked.exists():
        pytest.skip("Tracked OpenAPI export has not been generated yet")

    payload = json.loads(tracked.read_text(encoding="utf-8"))
    assert payload["info"]["title"] == "Synapse API"
    assert payload["info"]["version"] == _SYNAPSE_VERSION, (
        "docs/openapi.json is stale. Run `synapse-export-openapi` after bumping "
        "the version in pyproject.toml and commit the regenerated file."
    )
    assert "/health" in payload["paths"]
    assert "/knowledge/overview" in payload["paths"]
    assert "/ui/knowledge/bundles/{bundle_id}" in payload["paths"]
    assert "/ui/knowledge/operations" in payload["paths"]
