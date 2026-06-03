import pytest

from haystack_interface import IngestInput, OfflineProvider, build_engine


@pytest.mark.asyncio
async def test_offline_rerank_assigns_nonzero_score_for_relevant_doc() -> None:
    """Guard RERANK_QUERY_MARKER contract giữa RERANK_PROMPT (rerank.llm) và
    OfflineProvider._fake_rerank.

    Nếu dòng query trong prompt drift khỏi marker mà parser offline đọc, offline
    rerank âm thầm trả điểm 0 cho mọi đoạn (đã từng xảy ra khi bỏ dấu prompt).
    Test này bắt regression đó: doc khớp query phải có rerank_score > 0.
    """
    engine = build_engine(provider=OfflineProvider(256), caption=True)
    await engine.ingest(
        IngestInput(
            document_id="d-pw",
            document_name="Account",
            file_type="md",
            markdown="# Reset mật khẩu\nVào Cài đặt > Bảo mật để đặt lại mật khẩu.\n",
        )
    )

    results = await engine.search("reset mật khẩu", rerank_threshold=0.0)

    assert results
    assert results[0].rerank_score > 0, "offline rerank phải gán điểm > 0 cho doc khớp"
