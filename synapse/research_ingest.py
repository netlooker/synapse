"""Research bundle ingestion for source-first Synapse corpora."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .embeddings import EmbeddingClient, EmbeddingService
from .settings import load_settings
from .vector_store import VectorStore, create_vector_store


@dataclass(frozen=True)
class PreparedSource:
    source_id: str
    origin_url: str | None
    direct_paper_url: str | None
    title: str | None
    authors: list[str]
    published: str | None
    source_type: str | None
    retrieved_at: str | None
    extraction_status: str | None
    extraction_method: str | None
    summary_text: str | None
    abstract_text: str | None
    full_text: str | None
    full_text_path: str | None
    note_path: str | None
    metadata: dict[str, Any]
    artifact: dict[str, Any]


@dataclass(frozen=True)
class PreparedBundle:
    bundle_id: str
    metadata: dict[str, Any]
    artifact: dict[str, Any]
    sources: list[PreparedSource]


@dataclass(frozen=True)
class BundleIngestResult:
    bundle_id: str
    bundle_path: str
    replaced_existing: bool
    source_count: int
    segment_count: int


class ResearchBundleIngestor:
    """Normalize a prepared bundle artifact into the source-first Synapse schema."""

    def __init__(
        self,
        db: VectorStore,
        embedding_client: EmbeddingService,
        *,
        max_full_text_chars: int = 2400,
        target_full_text_tokens: int = 480,
    ):
        self.db = db
        self.embedding_client = embedding_client
        self.max_full_text_chars = max_full_text_chars
        self.target_full_text_tokens = target_full_text_tokens

    def ingest_bundle_file(self, bundle_path: Path) -> BundleIngestResult:
        bundle_path = bundle_path.expanduser().resolve()
        raw_text = bundle_path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
        prepared = normalize_prepared_bundle(payload, bundle_path)
        content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

        replaced_existing = False
        try:
            existing = self.db.get_bundle(prepared.bundle_id)
            if existing:
                self.db.delete_bundle(prepared.bundle_id, commit=False)
                replaced_existing = True

            bundle_row_id = self.db.upsert_bundle(
                prepared.bundle_id,
                content_hash,
                artifact_path=str(bundle_path),
                metadata=prepared.metadata,
                artifact=prepared.artifact,
                commit=False,
            )

            source_count = 0
            segment_count = 0
            for source in prepared.sources:
                source_row_id = self.db.insert_source(
                    bundle_row_id,
                    source.source_id,
                    origin_url=source.origin_url,
                    direct_paper_url=source.direct_paper_url,
                    title=source.title,
                    authors=source.authors,
                    published=source.published,
                    source_type=source.source_type,
                    retrieved_at=source.retrieved_at,
                    extraction_status=source.extraction_status,
                    extraction_method=source.extraction_method,
                    summary_text=source.summary_text,
                    abstract_text=source.abstract_text,
                    full_text=source.full_text,
                    full_text_path=source.full_text_path,
                    note_path=source.note_path,
                    metadata=source.metadata,
                    artifact=source.artifact,
                    commit=False,
                )
                source_count += 1

                segments = build_source_segments(
                    source,
                    max_full_text_chars=self.max_full_text_chars,
                    target_full_text_tokens=self.target_full_text_tokens,
                )
                if not segments:
                    continue
                embeddings = self.embedding_client.embed_document_chunks(
                    [text for _, text in segments],
                    document_title=source.title,
                    document_path=source.origin_url or source.direct_paper_url or source.source_id,
                )
                for index, ((role, text), embedding) in enumerate(zip(segments, embeddings)):
                    self.db.insert_segment(
                        owner_kind="source",
                        owner_id=source_row_id,
                        source_row_id=source_row_id,
                        content_role=role,
                        segment_index=index,
                        text=text,
                        embedding=embedding,
                        metadata={
                            "bundle_id": prepared.bundle_id,
                            "source_id": source.source_id,
                        },
                        commit=False,
                    )
                    segment_count += 1

            self.db.conn.commit()
        except Exception:
            self.db.conn.rollback()
            raise

        return BundleIngestResult(
            bundle_id=prepared.bundle_id,
            bundle_path=str(bundle_path),
            replaced_existing=replaced_existing,
            source_count=source_count,
            segment_count=segment_count,
        )


def normalize_prepared_bundle(payload: dict[str, Any], bundle_path: Path) -> PreparedBundle:
    bundle_section = payload.get("bundle")
    bundle_data = bundle_section if isinstance(bundle_section, dict) else {}
    bundle_id = _first_text(
        payload.get("bundle_id"),
        bundle_data.get("bundle_id"),
        bundle_data.get("id"),
    )
    if not bundle_id:
        raise ValueError(f"Prepared bundle {bundle_path} is missing bundle_id")

    raw_sources = _extract_sources(payload, bundle_data)
    if not raw_sources:
        raise ValueError(f"Prepared bundle {bundle_path} has no sources")

    metadata = {
        key: value
        for key, value in payload.items()
        if key not in {"sources", "prepared_sources", "bundle"}
    }
    if bundle_data:
        metadata["bundle"] = {
            key: value
            for key, value in bundle_data.items()
            if key != "sources"
        }

    return PreparedBundle(
        bundle_id=bundle_id,
        metadata=metadata,
        artifact=payload,
        sources=[normalize_prepared_source(item, bundle_path) for item in raw_sources],
    )


def normalize_prepared_source(raw_source: dict[str, Any], bundle_path: Path) -> PreparedSource:
    source_id = _first_text(raw_source.get("source_id"), raw_source.get("id"))
    if not source_id:
        raise ValueError(f"Prepared source in {bundle_path} is missing source_id")

    full_text_path = _resolve_optional_path(
        bundle_path.parent,
        _first_text(
            raw_source.get("full_text_path"),
            raw_source.get("text_path"),
            raw_source.get("sidecar_path"),
            raw_source.get("bundle_path"),
        ),
    )
    full_text = _normalize_text_field(raw_source.get("full_text"))
    if not full_text and full_text_path and full_text_path.exists():
        full_text = full_text_path.read_text(encoding="utf-8")

    authors = _normalize_authors(raw_source.get("authors"))
    return PreparedSource(
        source_id=source_id,
        origin_url=_normalize_url(raw_source.get("origin_url"), raw_source.get("origin"), raw_source.get("url")),
        direct_paper_url=_normalize_url(
            raw_source.get("direct_paper_url"),
            raw_source.get("paper_url"),
            raw_source.get("pdf_url"),
        ),
        title=_first_text(raw_source.get("title"), raw_source.get("name")),
        authors=authors,
        published=_first_text(raw_source.get("published"), raw_source.get("published_at")),
        source_type=_first_text(raw_source.get("source_type"), raw_source.get("type")),
        retrieved_at=_first_text(raw_source.get("retrieved_at"), raw_source.get("retrieved")),
        extraction_status=_first_text(raw_source.get("extraction_status"), raw_source.get("status")),
        extraction_method=_first_text(raw_source.get("extraction_method"), raw_source.get("method")),
        summary_text=_normalize_text_field(raw_source.get("summary")),
        abstract_text=_normalize_text_field(raw_source.get("abstract")),
        full_text=full_text,
        full_text_path=str(full_text_path) if full_text_path else None,
        note_path=_first_text(raw_source.get("note_path")),
        metadata={
            "json_mirror_path": _first_text(raw_source.get("json_path"), raw_source.get("json_mirror_path")),
        },
        artifact=raw_source,
    )


def build_source_segments(
    source: PreparedSource,
    *,
    max_full_text_chars: int = 2400,
    target_full_text_tokens: int = 480,
) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    if source.summary_text:
        segments.append(("summary", source.summary_text.strip()))
    if source.abstract_text:
        segments.extend(
            ("abstract", text)
            for text in _segment_text(source.abstract_text, max_chars=max_full_text_chars, target_tokens=target_full_text_tokens)
        )
    if source.full_text:
        segments.extend(
            ("full_text", text)
            for text in _segment_text(source.full_text, max_chars=max_full_text_chars, target_tokens=target_full_text_tokens)
        )
    return [(role, text) for role, text in segments if text.strip()]


def _extract_sources(payload: dict[str, Any], bundle_data: dict[str, Any]) -> list[dict[str, Any]]:
    for candidate in (
        payload.get("sources"),
        payload.get("prepared_sources"),
        bundle_data.get("sources"),
    ):
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _normalize_url(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, dict):
            candidate = _first_text(value.get("url"), value.get("href"))
            if candidate:
                return candidate
        candidate = _first_text(value)
        if candidate:
            return candidate
    return None


def _normalize_authors(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        authors = []
        for item in value:
            if isinstance(item, dict):
                author = _first_text(item.get("name"), item.get("display_name"))
            else:
                author = _first_text(item)
            if author:
                authors.append(author)
        return authors
    if isinstance(value, str):
        pieces = [part.strip() for part in value.split(",")]
        return [piece for piece in pieces if piece]
    return [str(value)]


def _normalize_text_field(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return _first_text(
            value.get("text"),
            value.get("content"),
            value.get("value"),
            value.get("summary"),
            value.get("abstract"),
        )
    return None


def _resolve_optional_path(root: Path, raw_value: str | None) -> Path | None:
    if not raw_value:
        return None
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = (root / path).resolve()
    return path


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def _segment_text(text: str, *, max_chars: int, target_tokens: int) -> list[str]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    if not paragraphs:
        return []
    segments: list[str] = []
    current_parts: list[str] = []
    current_chars = 0
    current_tokens = 0
    for paragraph in paragraphs:
        paragraph_chars = len(paragraph)
        paragraph_tokens = _estimate_tokens(paragraph)
        if current_parts and (
            current_chars + paragraph_chars > max_chars
            or current_tokens + paragraph_tokens > target_tokens
        ):
            segments.append("\n\n".join(current_parts).strip())
            current_parts = []
            current_chars = 0
            current_tokens = 0
        current_parts.append(paragraph)
        current_chars += paragraph_chars
        current_tokens += paragraph_tokens
    if current_parts:
        segments.append("\n\n".join(current_parts).strip())
    return segments


def _estimate_tokens(text: str) -> int:
    cleaned = " ".join(text.split())
    if not cleaned:
        return 0
    return max(1, round(len(cleaned) / 4))


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a prepared research bundle into Synapse.")
    parser.add_argument("bundle", help="Path to prepared_source_bundle.json")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to Synapse TOML config",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Override Synapse database path",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Embedding provider name to use for source segments",
    )
    args = parser.parse_args()

    settings = load_settings(args.config)
    provider = settings.embedding_provider(args.provider or settings.index.provider)
    db_path = Path(args.db or settings.database.path).expanduser()
    store = create_vector_store(settings, db_path=db_path, embedding_dim=provider.dimensions)
    store.initialize()
    try:
        ingestor = ResearchBundleIngestor(
            db=store,
            embedding_client=EmbeddingClient.from_provider(provider),
        )
        result = ingestor.ingest_bundle_file(Path(args.bundle))
    finally:
        store.close()

    print(f"📦 Ingested bundle {result.bundle_id}")
    print(f"   Path: {result.bundle_path}")
    print(f"   Sources: {result.source_count}")
    print(f"   Segments: {result.segment_count}")
    print(f"   Replaced Existing: {'yes' if result.replaced_existing else 'no'}")


if __name__ == "__main__":
    main()
