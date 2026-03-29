"""HTTP/OpenAPI adapter for Synapse and Cipher."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

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
    SearchRequest,
    SearchResponse,
    ValidateRequest,
    ValidateResponse,
    discover_index,
    index_vault,
    runtime_requirements,
    search_index,
    validate_index,
)
from .settings import load_settings


class CipherDepsModel(BaseModel):
    cortex_path: str
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
        version="0.1.0",
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
                CipherDeps(cortex_path=Path("."), synapse_db=Path(".")),
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
                CipherDeps(cortex_path=Path("."), synapse_db=Path(".")),
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
                CipherDeps(cortex_path=Path("."), synapse_db=Path(".")),
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
        cortex_path=Path(deps.cortex_path).expanduser(),
        synapse_db=Path(deps.synapse_db).expanduser(),
        wraith_root=Path(deps.wraith_root).expanduser() if deps.wraith_root else None,
    )


if __name__ == "__main__":
    main()
