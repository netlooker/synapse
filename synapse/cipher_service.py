"""Typed Cipher service facade."""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from .errors import SynapseDependencyError, SynapseTimeoutError, SynapseUnavailableError
from .settings import CipherSettings


@dataclass(frozen=True)
class CipherDeps:
    cortex_path: Path
    synapse_db: Path
    wraith_root: Path | None = None


class AuditVaultRequest(BaseModel):
    op: Literal["audit_vault"] = "audit_vault"
    mode: Literal["audit", "repair"] = "audit"


class ExplainConnectionRequest(BaseModel):
    op: Literal["explain_connection"] = "explain_connection"
    doc_a: str
    doc_b: str
    timeout_seconds: float | None = None


class SuggestChunkingStrategyRequest(BaseModel):
    op: Literal["suggest_chunking_strategy"] = "suggest_chunking_strategy"
    model_info: str
    timeout_seconds: float | None = None


class StubCandidate(BaseModel):
    target_link: str
    source_paths: list[str] = Field(default_factory=list)
    suggested_path: str | None = None


class ReviewStubCandidatesRequest(BaseModel):
    op: Literal["review_stub_candidates"] = "review_stub_candidates"
    candidates: list[StubCandidate] = Field(default_factory=list)
    stub_dir: str = "entities"
    timeout_seconds: float | None = None


CipherRequest = (
    AuditVaultRequest
    | ExplainConnectionRequest
    | SuggestChunkingStrategyRequest
    | ReviewStubCandidatesRequest
)


class AuditVaultResponse(BaseModel):
    status: str = "ok"
    summary: str
    broken_links: list[dict[str, str]] = Field(default_factory=list)
    stale_documents: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)


class ExplainConnectionResponse(BaseModel):
    status: str = "ok"
    explanation: str
    keywords: list[str] = Field(default_factory=list)


class SuggestChunkingStrategyResponse(BaseModel):
    status: str = "ok"
    max_chunk_size: int
    min_chunk_size: int
    rationale: str


class StubCandidateReview(BaseModel):
    target_link: str
    action: Literal["create_stub", "skip"] = "create_stub"
    rationale: str
    confidence: float = 0.5
    suggested_path: str | None = None


class ReviewStubCandidatesResponse(BaseModel):
    status: str = "ok"
    reviews: list[StubCandidateReview] = Field(default_factory=list)


CipherResponse = (
    AuditVaultResponse
    | ExplainConnectionResponse
    | SuggestChunkingStrategyResponse
    | ReviewStubCandidatesResponse
)


class CipherService:
    """Typed service facade for Cipher operations."""

    def __init__(self, model: str | object | None = None, settings: CipherSettings | None = None):
        self.model = model or os.environ.get("SYNAPSE_MODEL", "openai:glm-flash-64k:latest")
        self.settings = settings or CipherSettings()
        self._agent: Agent | None = None

    async def handle(self, request: CipherRequest, deps: CipherDeps) -> CipherResponse:
        if isinstance(request, AuditVaultRequest):
            return await self._audit_vault(request, deps)
        if isinstance(request, ExplainConnectionRequest):
            return await self._explain_connection(request)
        if isinstance(request, SuggestChunkingStrategyRequest):
            return await self._suggest_chunking_strategy(request)
        if isinstance(request, ReviewStubCandidatesRequest):
            return await self._review_stub_candidates(request)
        raise ValueError(f"Unsupported Cipher request: {type(request).__name__}")

    def _get_agent(self) -> Agent:
        if self._agent is None:
            self._agent = Agent(
                self.model,
                system_prompt=(
                    "You are Cipher, the reasoning layer for Synapse. "
                    "Be concise, evidence-oriented, and return practical answers."
                ),
            )
        return self._agent

    async def _audit_vault(self, request: AuditVaultRequest, deps: CipherDeps) -> AuditVaultResponse:
        broken_links = _scan_broken_links(deps.cortex_path)
        suggested_actions: list[str] = []
        if broken_links:
            suggested_actions.append("repair_links")
        if deps.synapse_db and not deps.synapse_db.exists():
            suggested_actions.append("reindex_documents")

        summary = "Vault audit complete."
        if broken_links:
            summary = f"{len(broken_links)} broken links detected."
        elif request.mode == "repair":
            summary = "No broken links found. No repairs needed."

        return AuditVaultResponse(
            summary=summary,
            broken_links=broken_links,
            stale_documents=[],
            suggested_actions=suggested_actions,
        )

    async def _explain_connection(self, request: ExplainConnectionRequest) -> ExplainConnectionResponse:
        prompt = (
            f"Explain why the markdown documents '{request.doc_a}' and '{request.doc_b}' are related. "
            "Keep the answer short and concrete."
        )
        result = await self._run_reasoning(
            prompt,
            timeout_seconds=(
                request.timeout_seconds
                if request.timeout_seconds is not None
                else self.settings.explain_timeout_seconds
            ),
        )
        explanation = str(result.output)
        return ExplainConnectionResponse(
            explanation=explanation,
            keywords=_keywords_from_text(explanation),
        )

    async def _suggest_chunking_strategy(
        self,
        request: SuggestChunkingStrategyRequest,
    ) -> SuggestChunkingStrategyResponse:
        prompt = (
            "Return a compact JSON object with keys max_chunk_size, min_chunk_size, and rationale. "
            f"Model info: {request.model_info}"
        )
        result = await self._run_reasoning(
            prompt,
            timeout_seconds=(
                request.timeout_seconds
                if request.timeout_seconds is not None
                else self.settings.chunking_timeout_seconds
            ),
        )
        raw = str(result.output)
        try:
            parsed = json.loads(raw)
            return SuggestChunkingStrategyResponse(**parsed)
        except Exception:
            return _heuristic_chunking_strategy(request.model_info, raw)

    async def _review_stub_candidates(
        self,
        request: ReviewStubCandidatesRequest,
    ) -> ReviewStubCandidatesResponse:
        if not request.candidates:
            return ReviewStubCandidatesResponse(reviews=[])

        prompt = (
            "You are reviewing proposed markdown stub notes for broken wikilinks. "
            "Return compact JSON with a top-level key 'reviews'. "
            "Each review must contain target_link, action ('create_stub' or 'skip'), "
            "rationale, confidence, and suggested_path. "
            "Prefer conservative creation: create stubs for likely note-worthy concepts, "
            "skip obvious noise, typos, or overly vague targets. "
            f"Stub directory: {request.stub_dir}. "
            f"Candidates: {request.model_dump_json()}"
        )
        result = await self._run_reasoning(
            prompt,
            timeout_seconds=(
                request.timeout_seconds
                if request.timeout_seconds is not None
                else self.settings.stub_review_timeout_seconds
            ),
        )
        raw = str(result.output)
        try:
            parsed = json.loads(raw)
            return ReviewStubCandidatesResponse(**parsed)
        except Exception:
            return _heuristic_stub_reviews(request)

    async def _run_reasoning(self, prompt: str, *, timeout_seconds: float) -> object:
        try:
            return await asyncio.wait_for(self._get_agent().run(prompt), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise SynapseTimeoutError(
                f"Cipher reasoning timed out after {timeout_seconds:.1f} seconds.",
                timeout_seconds=timeout_seconds,
            ) from exc
        except Exception as exc:
            message = str(exc)
            lower = message.lower()
            if "api_key" in lower or "api key" in lower:
                raise SynapseDependencyError(
                    "Cipher reasoning backend is not configured.",
                    dependency="reasoning_model",
                    retryable=False,
                ) from exc
            if "connection" in lower or "connect" in lower or "refused" in lower:
                raise SynapseUnavailableError(
                    "Cipher reasoning backend is unavailable.",
                    dependency="reasoning_model",
                ) from exc
            raise SynapseDependencyError(
                f"Cipher reasoning backend failed: {message}",
                dependency="reasoning_model",
            ) from exc


def _scan_broken_links(cortex_path: Path) -> list[dict[str, str]]:
    valid_targets: set[str] = set()
    markdown_files = list(cortex_path.rglob("*.md"))
    for file_path in markdown_files:
        valid_targets.add(file_path.stem.lower())

    broken_links: list[dict[str, str]] = []
    link_pattern = re.compile(r"\[\[([^\]]+)\]\]")
    for file_path in markdown_files:
        content = file_path.read_text(encoding="utf-8")
        for link in link_pattern.findall(content):
            base_link = link.split("#")[0].split("|")[0].strip()
            if not base_link:
                continue
            normalized = base_link.lower()
            if normalized in valid_targets:
                continue
            broken_links.append(
                {
                    "source_path": str(file_path),
                    "target_link": base_link,
                }
            )
    return broken_links


def _heuristic_chunking_strategy(
    model_info: str,
    rationale: str | None = None,
) -> SuggestChunkingStrategyResponse:
    lower = model_info.lower()
    max_chunk_size = 1800
    min_chunk_size = 300
    if "32k" in lower or "32000" in lower:
        max_chunk_size = 2200
        min_chunk_size = 360
    if "1024" in lower:
        max_chunk_size = max(max_chunk_size, 1800)
    return SuggestChunkingStrategyResponse(
        max_chunk_size=max_chunk_size,
        min_chunk_size=min_chunk_size,
        rationale=rationale or "Use medium chunks with room for contextual reranking.",
    )


def _heuristic_stub_reviews(
    request: ReviewStubCandidatesRequest,
) -> ReviewStubCandidatesResponse:
    reviews: list[StubCandidateReview] = []
    for candidate in request.candidates:
        token_count = len(_keywords_from_text(candidate.target_link))
        action: Literal["create_stub", "skip"] = "create_stub"
        confidence = 0.65
        rationale = "Broken link looks like a reusable note target."
        if token_count == 0 or len(candidate.target_link.strip()) <= 2:
            action = "skip"
            confidence = 0.35
            rationale = "Target is too small or vague to justify a stub."
        reviews.append(
            StubCandidateReview(
                target_link=candidate.target_link,
                action=action,
                rationale=rationale,
                confidence=confidence,
                suggested_path=candidate.suggested_path,
            )
        )
    return ReviewStubCandidatesResponse(reviews=reviews)


def _keywords_from_text(text: str) -> list[str]:
    tokens = [
        token
        for token in re.split(r"[^a-zA-Z0-9]+", text.lower())
        if len(token) >= 5
    ]
    seen: set[str] = set()
    keywords: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        keywords.append(token)
        if len(keywords) >= 5:
            break
    return keywords
