"""Self-test ingest-only offline bằng assert (không cần pytest / network):

    python -m core_engine.tests.selftest

Khóa các bất biến: embedder đúng dimension và tất định, ingest tạo chunk, payload
được ghi với full-content + lineage, idempotent (re-ingest không nhân đôi), delete
gỡ hết vector.
"""

from __future__ import annotations

import asyncio

from core_engine import build_engine, IngestInput, OfflineProvider
from core_engine.embedding import ProviderEmbeddingService
DIM = 256


async def _count_doc_chunks(engine, document_id: str) -> int:
    return len(await engine.vectors.list_chunk_ids_by_document(document_id))


async def run() -> None:
    try:
        import qdrant_client  # noqa: F401  (default provider qdrant in_process)
    except ModuleNotFoundError:
        print("SKIP - selftest can qdrant-client cho store mac dinh (pip install qdrant-client)")
        return
    provider = OfflineProvider(DIM)
    # caption=False => baseline embed child trực tiếp (tất định, dễ assert).
    engine = build_engine(provider=provider, caption=False)
    settings = engine.settings

    # 1. Embedder: đúng dimension, tất định (ingest==query).
    emb = ProviderEmbeddingService(provider, dimension=DIM)
    v1 = await emb.embed("reset mật khẩu")
    v2 = await emb.embed("reset mật khẩu")
    assert len(v1) == settings.embed_dimension == DIM, "sai dimension embed"
    assert v1 == v2, "embedder phải tất định (ingest==query)"

    # 2. Ingest tạo chunk.
    pw = IngestInput(
        document_id="d-pw", document_name="Account", file_type="md",
        markdown="# Reset mật khẩu\nVào Cài đặt > Bảo mật để đặt lại mật khẩu, link hết hạn 15 phút.\n",
    )
    n = await engine.ingest(pw)
    assert n >= 1, "ingest phải tạo >=1 chunk"

    await engine.ingest(IngestInput(
        document_id="d-sal", document_name="Salary", file_type="md",
        markdown="# Lương quý 2\nNgân sách lương quý 2 tăng 8 phần trăm.\n",
    ))

    # 3. Payload persist đủ full content + lineage.
    provider_impl = engine.vectors.provider
    client = getattr(provider_impl, "_client", None)
    assert client is not None, "selftest expects in-process Qdrant provider"
    result = client.scroll(
        collection_name=engine.vectors.config.index_id(),
        with_payload=True,
        with_vectors=False,
        limit=1000,
    )
    points = result[0] if isinstance(result, tuple) else result
    payloads = [point.payload or {} for point in points if (point.payload or {}).get("document_id") == "d-pw"]
    assert payloads, "ingest phải ghi payload cho document"
    assert any(payload.get("parent_text") for payload in payloads), "phải lưu full content"
    assert all(payload.get("source_uri") for payload in payloads), "phải có lineage source_uri"

    # 4. Idempotent: re-ingest cùng doc KHÔNG nhân đôi (OVERWRITE + id deterministic).
    before = await _count_doc_chunks(engine, "d-pw")
    await engine.ingest(pw)
    after = await _count_doc_chunks(engine, "d-pw")
    assert before == after, f"re-ingest phải idempotent: {before} -> {after}"

    # 5. delete_by_document gỡ hết vector.
    await engine.vectors.delete_by_document("d-pw")
    assert await _count_doc_chunks(engine, "d-pw") == 0, "xóa document phải gỡ hết vector"

    print("OK - all self-tests PASS")


if __name__ == "__main__":
    asyncio.run(run())
