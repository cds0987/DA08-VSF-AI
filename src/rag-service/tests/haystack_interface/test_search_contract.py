import pytest

from haystack_interface import IngestInput, OfflineProvider, build_engine


@pytest.mark.asyncio
async def test_engine_search_returns_contract_fields() -> None:
    engine = build_engine(provider=OfflineProvider(256), caption=True)
    await engine.ingest(
        IngestInput(
            document_id="doc-1",
            document_name="Account Guide",
            file_type="md",
            markdown="# Reset mật khẩu\nVào Cài đặt > Bảo mật để đặt lại mật khẩu.\n",
        )
    )

    results = await engine.search("reset mật khẩu", correlation_id="cid-001", rerank_threshold=0.0)

    assert results
    top = results[0]
    assert top.correlation_id == "cid-001"
    assert top.unit_id.startswith("doc-1::p0::c")
    assert top.display_name == "Account Guide"
    assert top.caption
    assert top.content
    assert top.heading_path == ["Reset mật khẩu"]
    assert top.lineage.source_uri == "local://doc-1"
    assert top.lineage.artifact_uri == "local://doc-1#artifact"


@pytest.mark.asyncio
async def test_engine_search_generates_correlation_id_when_missing() -> None:
    engine = build_engine(provider=OfflineProvider(256), caption=False)
    await engine.ingest(
        IngestInput(
            document_id="doc-2",
            document_name="HR Guide",
            file_type="md",
            markdown="# Leave\nQuy trình nghỉ phép năm.\n",
        )
    )

    results = await engine.search("nghỉ phép", rerank_threshold=0.0)

    assert results
    assert results[0].correlation_id
