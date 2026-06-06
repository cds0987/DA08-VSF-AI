import pytest

from core_engine import (
    IngestInput,
    OfflineProvider,
    build_engine,
)


def test_build_engine_reads_caption_enabled_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CAPTION_ENABLED", "false")

    engine = build_engine(provider=OfflineProvider(256))

    assert engine.captioner is None


@pytest.mark.asyncio
async def test_build_engine_ingests_without_search_wiring() -> None:
    engine = build_engine(provider=OfflineProvider(256), caption=False)
    await engine.ingest(
        IngestInput(
            document_id="doc-1",
            document_name="Account Guide",
            file_type="md",
            markdown="# Reset mật khẩu\nVào Cài đặt > Bảo mật để đặt lại mật khẩu.\n",
        )
    )

    assert await engine.vectors.list_chunk_ids_by_document("doc-1")
