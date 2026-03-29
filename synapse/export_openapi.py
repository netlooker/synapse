"""Export the Synapse OpenAPI document to a tracked file."""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_OPENAPI_PATH = Path("docs/openapi.json")


def export_openapi_spec(output_path: str | Path = DEFAULT_OPENAPI_PATH) -> Path:
    try:
        from .web_api import create_app
    except RuntimeError as exc:  # pragma: no cover - runtime dependency path
        raise RuntimeError(
            "FastAPI is required to export the Synapse OpenAPI spec. "
            "Install Synapse with the 'api' extra first."
        ) from exc

    app = create_app()
    payload = app.openapi()
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def main() -> None:
    destination = export_openapi_spec()
    print(destination)


if __name__ == "__main__":
    main()
