import pytest

from core_engine import (
    IngestInput,
    LexicalRerankerService,
    NoopRerankerService,
    OfflineProvider,
    build_engine,
)
from core_engine.rerank.llm import LLMReranker


def test_build_engine_reads_caption_enabled_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CAPTION_ENABLED", "false")

    engine = build_engine(provider=OfflineProvider(256))

    assert engine.captioner is None


@pytest.mark.parametrize(
    ("raw", "expected_type"),
    [
        ("llm", LLMReranker),
        ("lexical", LexicalRerankerService),
        ("none", NoopRerankerService),
    ],
)
def test_build_engine_reads_rerank_provider_from_env(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected_type: type,
) -> None:
    monkeypatch.setenv("RERANK_PROVIDER", raw)

    engine = build_engine(provider=OfflineProvider(256))

    assert isinstance(engine.reranker, expected_type)


@pytest.mark.asyncio
async def test_noop_reranker_keeps_vector_ranking_but_still_runs_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RERANK_PROVIDER", "none")

    engine = build_engine(provider=OfflineProvider(256), caption=False)
    await engine.ingest(
        IngestInput(
            document_id="doc-1",
            document_name="Account Guide",
            file_type="md",
            markdown="# Reset mật khẩu\nVào Cài đặt > Bảo mật để đặt lại mật khẩu.\n",
        )
    )

    results = await engine.search("reset mật khẩu", rerank_threshold=0.0)

    assert results
    assert all(result.rerank_score == result.score for result in results)
