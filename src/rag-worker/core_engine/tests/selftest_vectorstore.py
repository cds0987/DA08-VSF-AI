"""Self-test vectorstore facade + registry + contract chung (provider-first).

    python -m core_engine.tests.selftest_vectorstore

Kiến trúc: Application → VectorDB Interface → Registry (chọn provider) → package
provider (qdrant · chromadb · milvus). Mỗi provider có HAI file deployment, route
theo `config.url`: CÓ url → remote (async thuần); KO url → in_process (embedded,
to_thread). Không còn provider 'inmemory'.

Test chạm DB thật dùng qdrant in_process (`:memory:`); tự SKIP nếu chưa cài qdrant-client.
"""

from __future__ import annotations

import asyncio
import sys
from typing import List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.domain.repositories.vector_repository import SearchResult

from core_engine import IngestInput, OfflineProvider, build_engine
from core_engine.tests._contract import assert_vector_repository_contract
from core_engine.text_utils import hash_embed
from core_engine.vectorstore import (
    VectorRecord,
    VectorStoreConfig,
    VectorStoreProvider,
    available_providers,
    build_vector_repository,
    build_vector_store,
    register_backend,
)

DIM = 64


def _has_qdrant() -> bool:
    try:
        import qdrant_client  # noqa: F401
        return True
    except ModuleNotFoundError:
        return False


def _cfg(provider: str = "qdrant", url: str = "") -> VectorStoreConfig:
    return VectorStoreConfig(provider=provider, url=url, dimension=DIM)


async def test_registry_lists_providers() -> None:
    provs = available_providers()
    for expected in ("qdrant", "chromadb", "milvus"):
        assert expected in provs, f"registry thieu provider {expected!r}: {provs}"
    assert "inmemory" not in provs, "inmemory da bi go khoi danh sach provider"
    assert VectorStoreConfig().provider == "qdrant", "provider mac dinh phai la qdrant"
    print(f"  1. registry provider-first available={provs}, default=qdrant: OK")


async def test_deployment_derived_from_url() -> None:
    assert VectorStoreConfig().deployment == "in_process", "ko url -> in_process"
    assert VectorStoreConfig(url="http://h:6333").deployment == "remote", "co url -> remote"
    print("  2. deployment suy tu url: ko url=in_process, co url=remote: OK")


async def test_unknown_provider_raises() -> None:
    raised = ""
    try:
        build_vector_store(_cfg("khong_ton_tai"))
    except ValueError as e:
        raised = str(e)
    assert "chua dang ky" in raised and "qdrant" in raised, (
        f"phai raise kem danh sach: {raised!r}"
    )
    print("  3. provider la -> ValueError kem danh sach co san: OK")


async def test_pluggable_provider() -> None:
    built = {"n": 0}

    class FakeProvider(VectorStoreProvider):
        def __init__(self, config: VectorStoreConfig):
            super().__init__(config)
            built["n"] += 1

        async def insert_many(self, records) -> None: ...

        async def upsert_many(self, records) -> None: ...

        async def search(
            self, vector, query_text, top_k=20
        ) -> List[SearchResult]:
            return []

        async def list_chunk_ids_by_document(self, document_id) -> List[str]:
            return []

        async def delete_many(self, chunk_ids) -> None: ...

        async def delete_by_document(self, document_id) -> None: ...

    register_backend("fake_db", lambda c: FakeProvider(c))
    repo = build_vector_store(_cfg("fake_db"))
    assert isinstance(repo.provider, FakeProvider) and built["n"] == 1, (
        "provider dang ky phai build duoc"
    )
    dup_raised = False
    try:
        register_backend("fake_db", lambda c: FakeProvider(c))
    except ValueError:
        dup_raised = True
    assert dup_raised, "dang ky trung ten khong override phai raise"
    register_backend("fake_db", lambda c: FakeProvider(c), override=True)
    print("  4. dang ky provider moi + guardrail override im lang: OK")


async def test_providers_lazy_import() -> None:
    """Provider chưa cài lib -> ModuleNotFoundError hướng dẫn cài (lazy)."""
    import importlib

    checks = [("chromadb", "chromadb"), ("milvus", "pymilvus")]
    if not _has_qdrant():
        checks.append(("qdrant", "qdrant-client"))
    for provider, lib in checks:
        try:
            importlib.import_module(lib.replace("-", "_"))
            continue  # lib có sẵn -> bỏ qua kiểm tra lazy của provider này
        except ModuleNotFoundError:
            pass
        raised = ""
        try:
            build_vector_store(_cfg(provider))
        except ModuleNotFoundError as e:
            raised = str(e)
        assert lib in raised, f"provider {provider!r} thieu lib phai bao 'pip install {lib}': {raised!r}"
    print("  5. provider thieu lib -> bao pip install dung lib (lazy): OK")


async def test_url_routes_remote_vs_inprocess() -> None:
    if not _has_qdrant():
        print("  6. route deployment theo url: SKIP (chua cai qdrant-client)")
        return
    from core_engine.vectorstore.providers.qdrant.inprocess import (
        QdrantInProcessRepository,
    )
    from core_engine.vectorstore.providers.qdrant.remote import (
        QdrantRemoteRepository,
    )

    assert isinstance(build_vector_store(_cfg()), QdrantInProcessRepository), "ko url -> in_process"
    assert isinstance(
        build_vector_store(_cfg(url="http://localhost:6333")), QdrantRemoteRepository
    ), "co url -> remote"
    print("  6. route deployment theo url: ko url=in_process, co url=remote: OK")


async def test_engine_uses_selected_provider() -> None:
    if not _has_qdrant():
        print("  7. build_engine e2e: SKIP (chua cai qdrant-client cho in_process)")
        return
    from core_engine.vectorstore.providers.qdrant.inprocess import (
        QdrantInProcessRepository,
    )

    engine = build_engine(provider=OfflineProvider(DIM), caption=False)
    assert isinstance(engine.vectors, QdrantInProcessRepository)
    await engine.ingest(
        IngestInput(
            document_id="d1",
            document_name="Doc",
            file_type="md",
            markdown="# T\nreset mật khẩu trong cài đặt.\n",
        )
    )
    res = await engine.search("reset mật khẩu", rerank_threshold=0.0)
    assert res and res[0].document_id == "d1", "engine qua config object phai chay e2e"
    print("  7. build_engine dung provider qua config object + chay e2e: OK")


async def test_unified_interface_methods() -> None:
    if not _has_qdrant():
        print("  8. facade insert/upsert/search/delete: SKIP (chua cai qdrant-client)")
        return
    repo = build_vector_store(_cfg())

    text = "reset mật khẩu trong cài đặt bảo mật"
    vector = hash_embed([text], DIM)[0]
    payload = {
        "child_text": text,
        "bm25_text": text,
        "parent_id": "d2::p0",
        "parent_text": text,
        "document_id": "d2",
        "document_name": "Doc 2",
        "file_type": "md",
        "page_number": 1,
        "section_title": "T",
    }

    await repo.insert("d2::p0::c0", vector, payload)
    dup_raised = False
    try:
        await repo.insert("d2::p0::c0", vector, payload)
    except ValueError:
        dup_raised = True
    assert dup_raised, "insert trung id phai fail"

    await repo.upsert_many([VectorRecord(chunk_id="d2::p0::c1", vector=vector, payload=payload)])
    res = await repo.search(vector, "reset mật khẩu", top_k=10)
    assert any(r.document_id == "d2" for r in res), "search qua facade phai tim duoc doc"

    await repo.delete("d2::p0::c1")
    after_delete = await repo.search(vector, "reset mật khẩu", top_k=10)
    assert all(r.chunk_id != "d2::p0::c1" for r in after_delete), (
        "delete theo chunk_id phai go dung record"
    )

    await repo.delete_by_document("d2")
    after_doc_delete = await repo.search(vector, "reset mật khẩu", top_k=10)
    assert all(r.document_id != "d2" for r in after_doc_delete), (
        "delete_by_document phai go het record"
    )
    print("  8. facade async thong nhat insert/upsert/search/delete/delete_by_document: OK")


async def test_contract_qdrant_in_process() -> None:
    if not _has_qdrant():
        print("  9. contract test (qdrant in_process): SKIP (chua cai qdrant-client)")
        return
    from core_engine.vectorstore.providers.qdrant.inprocess import (
        QdrantInProcessRepository,
    )

    await assert_vector_repository_contract(QdrantInProcessRepository, dim=DIM)
    print("  9. contract test (qdrant in_process): dimension/idempotent/full-content/delete: OK")


async def run() -> None:
    await test_registry_lists_providers()
    await test_deployment_derived_from_url()
    await test_unknown_provider_raises()
    await test_pluggable_provider()
    await test_providers_lazy_import()
    await test_url_routes_remote_vs_inprocess()
    await test_engine_uses_selected_provider()
    await test_unified_interface_methods()
    await test_contract_qdrant_in_process()
    print("OK - vectorstore provider self-tests PASS")


if __name__ == "__main__":
    asyncio.run(run())
