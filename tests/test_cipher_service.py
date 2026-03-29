from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from synapse.cipher_service import (
    AuditVaultRequest,
    CipherDeps,
    CipherService,
    ExplainConnectionRequest,
    ReviewStubCandidatesRequest,
    SuggestChunkingStrategyRequest,
)
from synapse.errors import SynapseDependencyError, SynapseTimeoutError
from synapse.settings import CipherSettings


@pytest.mark.asyncio
async def test_cipher_service_explain_connection_is_lazy():
    model = TestModel(custom_output_text="These notes both describe semantic maintenance.")
    service = CipherService(model=model)

    assert service._agent is None

    response = await service.handle(
        ExplainConnectionRequest(doc_a="a.md", doc_b="b.md"),
        CipherDeps(cortex_path=Path("."), synapse_db=Path(".")),
    )

    assert "semantic maintenance" in response.explanation
    assert service._agent is not None


@pytest.mark.asyncio
async def test_cipher_service_audit_vault_finds_broken_links(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha\n\nLinks to [[Missing Note]]", encoding="utf-8")
    (vault / "beta.md").write_text("# Beta\n\nHealthy note.", encoding="utf-8")

    service = CipherService(model=TestModel(custom_output_text="Keep the vault tidy."))
    response = await service.handle(
        AuditVaultRequest(mode="audit"),
        CipherDeps(cortex_path=vault, synapse_db=tmp_path / "synapse.sqlite"),
    )

    assert response.status == "ok"
    assert len(response.broken_links) == 1
    assert response.broken_links[0]["target_link"] == "Missing Note"
    assert "repair_links" in response.suggested_actions


@pytest.mark.asyncio
async def test_cipher_service_returns_typed_chunking_strategy():
    model = TestModel(
        custom_output_text='{"max_chunk_size": 1800, "min_chunk_size": 300, "rationale": "Use medium chunks."}'
    )
    service = CipherService(model=model)

    response = await service.handle(
        SuggestChunkingStrategyRequest(model_info="1024-dim embeddings, 32k context"),
        CipherDeps(cortex_path=Path("."), synapse_db=Path(".")),
    )

    assert response.max_chunk_size == 1800
    assert response.min_chunk_size == 300


@pytest.mark.asyncio
async def test_cipher_service_reviews_stub_candidates():
    model = TestModel(
        custom_output_text=(
            '{"reviews": ['
            '{"target_link": "Semantic Memory", "action": "create_stub", '
            '"rationale": "This is a reusable concept note.", "confidence": 0.92, '
            '"suggested_path": "entities/Semantic Memory.md"}, '
            '{"target_link": "x", "action": "skip", '
            '"rationale": "Too vague.", "confidence": 0.21, '
            '"suggested_path": "entities/x.md"}'
            "]} "
        )
    )
    service = CipherService(model=model)

    response = await service.handle(
        ReviewStubCandidatesRequest(
            candidates=[
                {"target_link": "Semantic Memory", "source_paths": ["vault/a.md"]},
                {"target_link": "x", "source_paths": ["vault/b.md"]},
            ],
            stub_dir="entities",
        ),
        CipherDeps(cortex_path=Path("."), synapse_db=Path(".")),
    )

    assert response.reviews[0].action == "create_stub"
    assert response.reviews[1].action == "skip"


@pytest.mark.asyncio
async def test_cipher_service_explain_times_out(monkeypatch):
    class SlowAgent:
        async def run(self, prompt):
            await __import__("asyncio").sleep(0.05)
            return type("Result", (), {"output": "too slow"})()

    service = CipherService(settings=CipherSettings(explain_timeout_seconds=0.01))
    monkeypatch.setattr(service, "_get_agent", lambda: SlowAgent())

    with pytest.raises(SynapseTimeoutError) as exc_info:
        await service.handle(
            ExplainConnectionRequest(doc_a="a.md", doc_b="b.md"),
            CipherDeps(cortex_path=Path("."), synapse_db=Path(".")),
        )

    assert exc_info.value.timeout_seconds == 0.01


@pytest.mark.asyncio
async def test_cipher_service_wraps_reasoning_dependency_failure(monkeypatch):
    class BrokenAgent:
        async def run(self, prompt):
            raise RuntimeError("The api_key client option must be set")

    service = CipherService()
    monkeypatch.setattr(service, "_get_agent", lambda: BrokenAgent())

    with pytest.raises(SynapseDependencyError) as exc_info:
        await service.handle(
            ExplainConnectionRequest(doc_a="a.md", doc_b="b.md"),
            CipherDeps(cortex_path=Path("."), synapse_db=Path(".")),
        )

    assert exc_info.value.dependency == "reasoning_model"
