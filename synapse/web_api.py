"""HTTP/OpenAPI adapter for Synapse and Cipher."""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version as _package_version
from pathlib import Path

from pydantic import BaseModel


def _resolve_synapse_version() -> str:
    """Return the authoritative Synapse version.

    Prefers ``pyproject.toml`` when running from an editable install or source
    checkout, because editable installs do not refresh their metadata when the
    version in ``pyproject.toml`` is bumped. Falls back to the installed
    package metadata for wheel installs where ``pyproject.toml`` is not
    shipped but the version is baked into ``PKG-INFO`` at build time.
    """
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject.is_file():
        try:
            with pyproject.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):  # pragma: no cover - defensive
            data = {}
        version = data.get("project", {}).get("version")
        if isinstance(version, str) and version:
            return version
    try:
        return _package_version("synapse")
    except PackageNotFoundError:  # pragma: no cover - uninstalled source checkout
        return "0.0.0+unknown"


_SYNAPSE_VERSION = _resolve_synapse_version()

try:  # pragma: no cover - exercised by runtime install path
    from fastapi.responses import HTMLResponse, RedirectResponse
except ImportError:  # pragma: no cover
    HTMLResponse = None  # type: ignore[assignment]
    RedirectResponse = None  # type: ignore[assignment]

from .cipher_service import (
    AuditVaultRequest,
    CipherDeps,
    CipherService,
    ExplainConnectionRequest,
    ExplainConnectionResponse,
    ReviewStubCandidatesRequest,
    ReviewStubCandidatesResponse,
    SuggestChunkingStrategyRequest,
    SuggestChunkingStrategyResponse,
    AuditVaultResponse,
)
from .errors import SynapseError
from .service_api import (
    DiscoverRequest,
    DiscoverResponse,
    HealthRequest,
    HealthResponse,
    IndexRequest,
    IndexResponse,
    IngestBundleRequest,
    IngestBundleResponse,
    KnowledgeApplyResponse,
    KnowledgeBundleDetailRequest,
    KnowledgeCompileBundleRequest,
    KnowledgeCompileBundleResponse,
    KnowledgeOverviewRequest,
    KnowledgeOverviewResponse,
    KnowledgeProposalActionRequest,
    KnowledgeProposalListRequest,
    KnowledgeProposalListResponse,
    KnowledgeRejectResponse,
    KnowledgeSourceDetailRequest,
    SearchRequest,
    SearchResponse,
    ValidateRequest,
    ValidateResponse,
    apply_knowledge_proposal,
    compile_knowledge_bundle,
    discover_index,
    index_vault,
    ingest_bundle_artifact,
    knowledge_bundle_detail,
    knowledge_overview,
    knowledge_source_detail,
    list_knowledge_proposals,
    reject_knowledge_proposal,
    runtime_requirements,
    search_index,
    validate_index,
)
from .knowledge_ui import (
    render_bundle_detail_page,
    render_library_page,
    render_logs_page,
    render_note_detail_page,
    render_operations_page,
    render_overview_page,
    render_proposal_queue_page,
    render_sources_page,
    render_source_detail_page,
)
from .knowledge_schema import managed_index_path, managed_log_path
from .settings import load_settings


class CipherDepsModel(BaseModel):
    vault_root: str
    synapse_db: str
    wraith_root: str | None = None


class CipherAuditApiRequest(AuditVaultRequest):
    deps: CipherDepsModel
    config_path: str | None = None


class CipherExplainApiRequest(ExplainConnectionRequest):
    config_path: str | None = None


class CipherChunkingApiRequest(SuggestChunkingStrategyRequest):
    config_path: str | None = None


class CipherStubReviewApiRequest(ReviewStubCandidatesRequest):
    config_path: str | None = None


class ErrorResponse(BaseModel):
    error_type: str
    message: str
    retryable: bool
    dependency: str | None = None
    timeout_seconds: float | None = None


def create_app(cipher_service: CipherService | None = None):
    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as exc:  # pragma: no cover - exercised by runtime install path
        raise RuntimeError(
            "FastAPI is not installed. Install Synapse with the 'api' extra, for example: "
            "pip install -e '.[api]'"
        ) from exc

    cipher = cipher_service or CipherService()

    app = FastAPI(
        title="Synapse API",
        summary="HTTP and OpenAPI interface for Synapse retrieval and Cipher reasoning.",
        version=_SYNAPSE_VERSION,
        description=(
            "Expose Synapse indexing, search, discovery, validation, and Cipher operations "
            "over JSON/HTTP for PWAs and other web clients."
        ),
    )

    def map_error(exc: Exception) -> HTTPException:
        if isinstance(exc, SynapseError):
            return HTTPException(status_code=exc.status_code, detail=exc.to_dict())
        if isinstance(exc, FileNotFoundError):
            return HTTPException(status_code=404, detail={"error_type": "not_found", "message": str(exc), "retryable": False})
        if isinstance(exc, ValueError):
            return HTTPException(status_code=400, detail={"error_type": "bad_request", "message": str(exc), "retryable": False})
        return HTTPException(status_code=500, detail=str(exc))

    @app.get("/health", response_model=HealthResponse, tags=["synapse"])
    def get_health(
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
        note_provider: str | None = None,
        chunk_provider: str | None = None,
    ) -> HealthResponse:
        try:
            return runtime_requirements(
                HealthRequest(
                    config_path=config_path,
                    vault_root=vault_root,
                    db_path=db_path,
                    note_provider=note_provider,
                    chunk_provider=chunk_provider,
                )
            )
        except Exception as exc:  # pragma: no cover - exercised through tests
            raise map_error(exc) from exc

    @app.post("/index", response_model=IndexResponse, tags=["synapse"], responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 424: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
    def post_index(request: IndexRequest) -> IndexResponse:
        try:
            return index_vault(request)
        except Exception as exc:  # pragma: no cover - exercised through tests
            raise map_error(exc) from exc

    @app.post("/search", response_model=SearchResponse, tags=["synapse"], responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 424: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
    def post_search(request: SearchRequest) -> SearchResponse:
        try:
            return search_index(request)
        except Exception as exc:  # pragma: no cover - exercised through tests
            raise map_error(exc) from exc

    @app.post("/discover", response_model=DiscoverResponse, tags=["synapse"], responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 424: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
    def post_discover(request: DiscoverRequest) -> DiscoverResponse:
        try:
            return discover_index(request)
        except Exception as exc:  # pragma: no cover - exercised through tests
            raise map_error(exc) from exc

    @app.post("/validate", response_model=ValidateResponse, tags=["synapse"], responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
    def post_validate(request: ValidateRequest) -> ValidateResponse:
        try:
            return validate_index(request)
        except Exception as exc:  # pragma: no cover - exercised through tests
            raise map_error(exc) from exc

    @app.post(
        "/ingest-bundle",
        response_model=IngestBundleResponse,
        tags=["synapse"],
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def post_ingest_bundle(request: IngestBundleRequest) -> IngestBundleResponse:
        try:
            return ingest_bundle_artifact(request)
        except Exception as exc:  # pragma: no cover - exercised through tests
            raise map_error(exc) from exc

    # ------------------------------------------------------------------
    # Compiled knowledge layer (optional)
    # ------------------------------------------------------------------

    @app.post(
        "/knowledge/compile/bundle",
        response_model=KnowledgeCompileBundleResponse,
        tags=["knowledge"],
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def post_knowledge_compile_bundle(
        request: KnowledgeCompileBundleRequest,
    ) -> KnowledgeCompileBundleResponse:
        try:
            return compile_knowledge_bundle(request)
        except Exception as exc:  # pragma: no cover - exercised through tests
            raise map_error(exc) from exc

    @app.get(
        "/knowledge/overview",
        response_model=KnowledgeOverviewResponse,
        tags=["knowledge"],
        responses={404: {"model": ErrorResponse}},
    )
    def get_knowledge_overview(
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
    ) -> KnowledgeOverviewResponse:
        try:
            return knowledge_overview(
                KnowledgeOverviewRequest(
                    config_path=config_path,
                    vault_root=vault_root,
                    db_path=db_path,
                )
            )
        except Exception as exc:  # pragma: no cover
            raise map_error(exc) from exc

    @app.get(
        "/knowledge/proposals",
        response_model=KnowledgeProposalListResponse,
        tags=["knowledge"],
        responses={404: {"model": ErrorResponse}},
    )
    def get_knowledge_proposals(
        status: str | None = None,
        limit: int | None = None,
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
    ) -> KnowledgeProposalListResponse:
        try:
            return list_knowledge_proposals(
                KnowledgeProposalListRequest(
                    status=status,
                    limit=limit,
                    config_path=config_path,
                    vault_root=vault_root,
                    db_path=db_path,
                )
            )
        except Exception as exc:  # pragma: no cover
            raise map_error(exc) from exc

    @app.post(
        "/knowledge/proposals/{proposal_id}/apply",
        response_model=KnowledgeApplyResponse,
        tags=["knowledge"],
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    def post_knowledge_apply(
        proposal_id: int, request: KnowledgeProposalActionRequest | None = None
    ) -> KnowledgeApplyResponse:
        try:
            return apply_knowledge_proposal(
                proposal_id,
                request or KnowledgeProposalActionRequest(),
            )
        except Exception as exc:  # pragma: no cover
            raise map_error(exc) from exc

    @app.post(
        "/knowledge/proposals/{proposal_id}/reject",
        response_model=KnowledgeRejectResponse,
        tags=["knowledge"],
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
        },
    )
    def post_knowledge_reject(
        proposal_id: int, request: KnowledgeProposalActionRequest | None = None
    ) -> KnowledgeRejectResponse:
        try:
            return reject_knowledge_proposal(
                proposal_id,
                request or KnowledgeProposalActionRequest(),
            )
        except Exception as exc:  # pragma: no cover
            raise map_error(exc) from exc

    # ------------------------------------------------------------------
    # Thin server-rendered UI
    # ------------------------------------------------------------------

    def _knowledge_ui_request(
        *,
        config_path: str | None,
        vault_root: str | None,
        db_path: str | None,
        status: str | None = None,
        limit: int | None = None,
    ) -> tuple[KnowledgeOverviewResponse, list[dict], str]:
        overview = knowledge_overview(
            KnowledgeOverviewRequest(
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
            )
        )
        listing = list_knowledge_proposals(
            KnowledgeProposalListRequest(
                status=status,
                limit=limit,
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
            )
        )
        return overview, [item.model_dump() for item in listing.proposals], str(
            Path(overview.vault_root) / managed_log_path(overview.managed_root)
        )

    def _read_text_if_exists(path: Path) -> str:
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
        return ""

    def _parse_log_entries(raw_log: str) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for line in raw_log.splitlines():
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue
            payload = stripped[2:]
            if " :: " in payload:
                timestamp, message = payload.split(" :: ", 1)
            else:
                timestamp, message = "", payload
            entries.append({"timestamp": timestamp, "message": message})
        return list(reversed(entries[-25:]))

    def _source_index(proposals: list[dict]) -> list[dict[str, object]]:
        grouped: dict[tuple[str, str], dict[str, object]] = {}
        for proposal in proposals:
            refs = proposal.get("supporting_refs") or {}
            bundle_id = str(refs.get("bundle_id") or "").strip()
            source_id = str(refs.get("source_id") or "").strip()
            if not bundle_id or not source_id:
                continue
            key = (bundle_id, source_id)
            row = grouped.setdefault(
                key,
                {
                    "bundle_id": bundle_id,
                    "source_id": source_id,
                    "title": proposal.get("title") or source_id,
                    "proposal_count": 0,
                    "applied_count": 0,
                    "latest_status": proposal.get("status") or "",
                    "latest_at": proposal.get("updated_at") or proposal.get("created_at") or "",
                },
            )
            row["proposal_count"] = int(row["proposal_count"]) + 1
            if proposal.get("status") == "applied":
                row["applied_count"] = int(row["applied_count"]) + 1
            current_stamp = str(proposal.get("updated_at") or proposal.get("created_at") or "")
            if current_stamp >= str(row["latest_at"]):
                row["latest_at"] = current_stamp
                row["latest_status"] = str(proposal.get("status") or "")
                row["title"] = proposal.get("title") or row["title"]
        return sorted(
            grouped.values(),
            key=lambda row: (
                str(row.get("latest_at") or ""),
                str(row.get("bundle_id") or ""),
                str(row.get("source_id") or ""),
            ),
            reverse=True,
        )

    @app.get("/ui/knowledge/", response_class=HTMLResponse, tags=["knowledge-ui"])
    def ui_overview(
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
    ) -> HTMLResponse:
        try:
            overview, _, _ = _knowledge_ui_request(
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
                limit=12,
            )
        except Exception as exc:
            raise map_error(exc) from exc
        html = render_overview_page(
            managed_root=overview.managed_root,
            vault_root=overview.vault_root,
            counts=overview.counts,
            recent_proposals=[item.model_dump() for item in overview.recent_proposals],
        )
        return HTMLResponse(content=html)

    @app.get("/ui/knowledge/sources", response_class=HTMLResponse, tags=["knowledge-ui"])
    def ui_sources(
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
    ) -> HTMLResponse:
        try:
            _, proposals, _ = _knowledge_ui_request(
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
            )
        except Exception as exc:
            raise map_error(exc) from exc
        return HTMLResponse(content=render_sources_page(sources=_source_index(proposals)))

    @app.get(
        "/ui/knowledge/bundles/{bundle_id}",
        response_class=HTMLResponse,
        tags=["knowledge-ui"],
    )
    def ui_bundle_detail(
        bundle_id: str,
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
    ) -> HTMLResponse:
        try:
            response = knowledge_bundle_detail(
                KnowledgeBundleDetailRequest(
                    bundle_id=bundle_id,
                    config_path=config_path,
                    vault_root=vault_root,
                    db_path=db_path,
                )
            )
        except Exception as exc:
            raise map_error(exc) from exc
        return HTMLResponse(
            content=render_bundle_detail_page(
                bundle_id=bundle_id,
                bundle=response.bundle,
                sources=[item.model_dump() for item in response.sources],
            )
        )

    @app.get(
        "/ui/knowledge/sources/{bundle_id}/{source_id}",
        response_class=HTMLResponse,
        tags=["knowledge-ui"],
    )
    def ui_source_detail(
        bundle_id: str,
        source_id: str,
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
    ) -> HTMLResponse:
        try:
            response = knowledge_source_detail(
                KnowledgeSourceDetailRequest(
                    bundle_id=bundle_id,
                    source_id=source_id,
                    config_path=config_path,
                    vault_root=vault_root,
                    db_path=db_path,
                )
            )
        except Exception as exc:
            raise map_error(exc) from exc
        html = render_source_detail_page(
            bundle_id=bundle_id,
            source_id=source_id,
            source=response.source,
            related_proposals=[item.model_dump() for item in response.related_proposals],
            segments=[item.model_dump() for item in response.segments],
        )
        return HTMLResponse(content=html)

    @app.get("/ui/knowledge/library", response_class=HTMLResponse, tags=["knowledge-ui"])
    def ui_library(
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
    ) -> HTMLResponse:
        try:
            _, proposals, _ = _knowledge_ui_request(
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
                status="applied",
            )
        except Exception as exc:
            raise map_error(exc) from exc
        return HTMLResponse(content=render_library_page(proposals=proposals))

    @app.get("/ui/knowledge/proposals", response_class=HTMLResponse, tags=["knowledge-ui"])
    def ui_proposal_queue(
        status: str | None = None,
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
    ) -> HTMLResponse:
        try:
            _, proposals, _ = _knowledge_ui_request(
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
                status=status,
            )
        except Exception as exc:
            raise map_error(exc) from exc
        html = render_proposal_queue_page(
            proposals=proposals,
        )
        return HTMLResponse(content=html)

    @app.get(
        "/ui/knowledge/proposals/{proposal_id}",
        response_class=HTMLResponse,
        tags=["knowledge-ui"],
    )
    def ui_proposal_detail(
        proposal_id: int,
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
    ) -> HTMLResponse:
        try:
            listing = list_knowledge_proposals(
                KnowledgeProposalListRequest(
                    config_path=config_path,
                    vault_root=vault_root,
                    db_path=db_path,
                )
            )
        except Exception as exc:
            raise map_error(exc) from exc
        match = next(
            (item.model_dump() for item in listing.proposals if item.id == proposal_id),
            None,
        )
        if match is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_type": "not_found",
                    "message": f"Proposal not found: {proposal_id}",
                    "retryable": False,
                },
            )
        return HTMLResponse(content=render_note_detail_page(proposal=match))

    @app.get("/ui/knowledge/operations", response_class=HTMLResponse, tags=["knowledge-ui"])
    def ui_operations(
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
    ) -> HTMLResponse:
        try:
            overview, proposals, log_path = _knowledge_ui_request(
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
            )
        except Exception as exc:
            raise map_error(exc) from exc
        raw_log = _read_text_if_exists(Path(log_path))
        html = render_operations_page(
            managed_root=overview.managed_root,
            vault_root=overview.vault_root,
            counts=overview.counts,
            recent_proposals=sorted(
                proposals,
                key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""),
                reverse=True,
            )[:12],
            log_entries=_parse_log_entries(raw_log),
            artifacts={
                "index_path": str(Path(overview.vault_root) / managed_index_path(overview.managed_root)),
                "log_path": log_path,
            },
        )
        return HTMLResponse(content=html)

    @app.get("/ui/knowledge/logs", response_class=HTMLResponse, tags=["knowledge-ui"])
    def ui_logs(
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
    ) -> HTMLResponse:
        try:
            overview, _, log_path = _knowledge_ui_request(
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
            )
        except Exception as exc:
            raise map_error(exc) from exc
        del overview
        raw_log = _read_text_if_exists(Path(log_path))
        return HTMLResponse(
            content=render_logs_page(
                log_path=log_path,
                log_entries=_parse_log_entries(raw_log),
                raw_log=raw_log,
            )
        )

    @app.post(
        "/ui/knowledge/proposals/{proposal_id}/apply",
        tags=["knowledge-ui"],
    )
    def ui_apply(
        proposal_id: int,
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
    ):
        try:
            apply_knowledge_proposal(
                proposal_id,
                KnowledgeProposalActionRequest(
                    config_path=config_path,
                    vault_root=vault_root,
                    db_path=db_path,
                ),
            )
        except Exception as exc:
            raise map_error(exc) from exc
        return RedirectResponse(url="/ui/knowledge/proposals", status_code=303)

    @app.post(
        "/ui/knowledge/proposals/{proposal_id}/reject",
        tags=["knowledge-ui"],
    )
    def ui_reject(
        proposal_id: int,
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
    ):
        try:
            reject_knowledge_proposal(
                proposal_id,
                KnowledgeProposalActionRequest(
                    config_path=config_path,
                    vault_root=vault_root,
                    db_path=db_path,
                ),
            )
        except Exception as exc:
            raise map_error(exc) from exc
        return RedirectResponse(url="/ui/knowledge/proposals", status_code=303)

    @app.get("/cipher/health", response_model=HealthResponse, tags=["cipher"])
    def get_cipher_health(config_path: str | None = None) -> HealthResponse:
        try:
            return runtime_requirements(HealthRequest(config_path=config_path))
        except Exception as exc:  # pragma: no cover
            raise map_error(exc) from exc

    @app.post(
        "/cipher/audit",
        response_model=AuditVaultResponse,
        tags=["cipher"],
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    async def post_cipher_audit(request: CipherAuditApiRequest) -> AuditVaultResponse:
        try:
            settings = load_settings(request.config_path)
            cipher.settings = settings.cipher
            return await cipher.handle(
                AuditVaultRequest(mode=request.mode),
                _cipher_deps(request.deps),
            )
        except Exception as exc:  # pragma: no cover - exercised through tests
            raise map_error(exc) from exc

    @app.post(
        "/cipher/explain",
        response_model=ExplainConnectionResponse,
        tags=["cipher"],
        responses={424: {"model": ErrorResponse}, 503: {"model": ErrorResponse}, 504: {"model": ErrorResponse}},
    )
    async def post_cipher_explain(request: CipherExplainApiRequest) -> ExplainConnectionResponse:
        try:
            settings = load_settings(request.config_path)
            cipher.settings = settings.cipher
            return await cipher.handle(
                ExplainConnectionRequest(
                    doc_a=request.doc_a,
                    doc_b=request.doc_b,
                    timeout_seconds=request.timeout_seconds,
                ),
                CipherDeps(vault_root=Path("."), synapse_db=Path(".")),
            )
        except Exception as exc:  # pragma: no cover - exercised through tests
            raise map_error(exc) from exc

    @app.post(
        "/cipher/chunking-strategy",
        response_model=SuggestChunkingStrategyResponse,
        tags=["cipher"],
        responses={424: {"model": ErrorResponse}, 503: {"model": ErrorResponse}, 504: {"model": ErrorResponse}},
    )
    async def post_cipher_chunking_strategy(
        request: CipherChunkingApiRequest,
    ) -> SuggestChunkingStrategyResponse:
        try:
            settings = load_settings(request.config_path)
            cipher.settings = settings.cipher
            return await cipher.handle(
                SuggestChunkingStrategyRequest(
                    model_info=request.model_info,
                    timeout_seconds=request.timeout_seconds,
                ),
                CipherDeps(vault_root=Path("."), synapse_db=Path(".")),
            )
        except Exception as exc:  # pragma: no cover - exercised through tests
            raise map_error(exc) from exc

    @app.post(
        "/cipher/review-stubs",
        response_model=ReviewStubCandidatesResponse,
        tags=["cipher"],
        responses={424: {"model": ErrorResponse}, 503: {"model": ErrorResponse}, 504: {"model": ErrorResponse}},
    )
    async def post_cipher_review_stubs(
        request: CipherStubReviewApiRequest,
    ) -> ReviewStubCandidatesResponse:
        try:
            settings = load_settings(request.config_path)
            cipher.settings = settings.cipher
            return await cipher.handle(
                ReviewStubCandidatesRequest(
                    candidates=request.candidates,
                    stub_dir=request.stub_dir,
                    timeout_seconds=request.timeout_seconds,
                ),
                CipherDeps(vault_root=Path("."), synapse_db=Path(".")),
            )
        except Exception as exc:  # pragma: no cover - exercised through tests
            raise map_error(exc) from exc

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(
        "synapse.web_api:create_app",
        factory=True,
        host="127.0.0.1",
        port=8765,
        reload=False,
    )


def _cipher_deps(deps: CipherDepsModel) -> CipherDeps:
    return CipherDeps(
        vault_root=Path(deps.vault_root).expanduser(),
        synapse_db=Path(deps.synapse_db).expanduser(),
        wraith_root=Path(deps.wraith_root).expanduser() if deps.wraith_root else None,
    )


if __name__ == "__main__":
    main()
