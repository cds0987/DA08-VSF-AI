"""Self-test BẤT ĐỒNG BỘ — kiểm tra async qua các giai đoạn pipeline:

    python -m haystack_interface.tests.selftest_async

Bám docs:
- embedding.md §1: embed là I/O-bound → async-native trả công (gather nhiều call
  provider đồng thời). search.md §8: search & ingest chia sẻ embedder.
- providers/*: client SYNC (vd chromadb/milvus) bọc `asyncio.to_thread` để KHÔNG
  chặn event loop; client async-native (qdrant) thì async thuần.
- embedding.md §2: idempotent response mapping — request ↔ vector đúng thứ tự.
- LESSONS §4.9: mọi AI call retry+backoff+jitter đồng nhất (retry_async).

Tất cả offline, tất định, không mạng. Mốc thời gian đặt lỏng để không flaky.
"""

from __future__ import annotations

import asyncio
import sys
import time
from types import SimpleNamespace
from typing import List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.domain.repositories.embedding_service import EmbeddingService
from app.domain.repositories.vector_repository import VectorRepository

from haystack_interface import IngestInput, OfflineProvider, OpenAIProvider, ProviderEmbeddingService
from haystack_interface.ai import retry_async
from haystack_interface.ai.base import AISettings, CapabilityConfig
from haystack_interface.config import HaystackSettings
from haystack_interface.engine import HaystackRagEngine
from haystack_interface.text_utils import hash_embed, overlap_score
from haystack_interface.vectorstore import VectorStoreConfig

DIM = 64


def _has_qdrant() -> bool:
    try:
        import qdrant_client  # noqa: F401
        return True
    except ModuleNotFoundError:
        return False


def _vectors():
    """Store chạm DB cho test async: qdrant in_process (embedded, không server)."""
    from haystack_interface.vectorstore.providers.qdrant.inprocess import (
        QdrantInProcessRepository,
    )
    return QdrantInProcessRepository(VectorStoreConfig(dimension=DIM))


async def _count_chunks(repo) -> int:
    """Đếm chunk backend-agnostic: search top_k lớn -> số chunk_id distinct."""
    res = await repo.search(hash_embed(["count"], DIM)[0], "count", top_k=100000)
    return len({r.chunk_id for r in res})


# --- Fakes mô phỏng I/O-bound (await sleep) cho stage embed & rerank ---------- #
class SleepEmbedder(EmbeddingService):
    """Embedder I/O-bound giả: await sleep rồi hash-embed tất định."""

    def __init__(self, dim: int, delay: float):
        self.dim, self.delay = dim, delay

    async def embed(self, text: str) -> List[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        await asyncio.sleep(self.delay)
        return hash_embed(texts, self.dim)


class SleepReranker:
    def __init__(self, delay: float):
        self.delay = delay

    async def rerank(self, query, results, top_k, threshold):
        await asyncio.sleep(self.delay)
        for r in results:
            r.rerank_score = overlap_score(query, r.parent_text or r.child_text)
        results.sort(key=lambda r: r.rerank_score, reverse=True)
        return [r for r in results if r.rerank_score >= threshold][:top_k]


def _doc(i: int) -> IngestInput:
    return IngestInput(
        document_id=f"d{i}", document_name=f"Doc {i}", file_type="md",
        markdown=f"# Section {i}\nNội dung tài liệu số {i} với từ khoá word{i} đặc trưng.\n",
    )


# --------------------------------------------------------------------------- #
# A. I/O-bound concurrency: gather nhiều search CHỒNG nhau (không tuần tự)      #
# --------------------------------------------------------------------------- #
async def test_io_concurrency_overlap() -> None:
    if not _has_qdrant():
        print("  A. I/O concurrency: SKIP (chua cai qdrant-client cho store in_process)")
        return
    settings = HaystackSettings(embed_dimension=DIM)
    engine = HaystackRagEngine(
        settings=settings,
        embedder=SleepEmbedder(DIM, 0.1),
        vectors=_vectors(),
        reranker=SleepReranker(0.1),
        captioner=None,
    )
    await engine.ingest(_doc(1))

    N = 10
    t0 = time.perf_counter()
    results = await asyncio.gather(
        *[engine.search("word1", rerank_threshold=0.0) for _ in range(N)]
    )
    elapsed = time.perf_counter() - t0

    # Mỗi search ~ embed(0.1)+rerank(0.1)=0.2s. Tuần tự N=10 -> ~2.0s.
    # Async chồng nhau -> ~0.3-0.5s. Mốc <1.5s (nới cho máy bận) vẫn << 2.0s serial.
    assert all(r for r in results), "mọi search concurrent phải có kết quả"
    assert elapsed < 1.5, f"search không chồng async (tuần tự ~2.0s?): {elapsed:.2f}s"
    print(f"  A. I/O concurrency: {N} search chồng nhau trong {elapsed:.2f}s (<1.5, serial~2.0): OK")


# --------------------------------------------------------------------------- #
# B. Blocking store offload to_thread => KHÔNG chặn event loop                  #
# --------------------------------------------------------------------------- #
class _BlockingStore(VectorRepository):
    """Mô phỏng đúng pattern provider sync (chroma/milvus): blocking bọc to_thread."""

    async def upsert(self, chunk_id, vector, payload) -> None: ...
    async def upsert_many(self, records) -> None: ...
    async def list_chunk_ids_by_document(self, document_id) -> list: return []
    async def delete_many(self, chunk_ids) -> None: ...
    async def delete_by_document(self, document_id) -> None: ...

    async def hybrid_search(self, vector, query_text, top_k=20):
        await asyncio.to_thread(time.sleep, 0.3)   # blocking CPU/I/O -> thread
        return []


async def test_blocking_offload_keeps_loop_alive() -> None:
    store = _BlockingStore()

    async def ticker() -> int:
        n = 0
        for _ in range(30):
            await asyncio.sleep(0.01)
            n += 1
        return n

    # CONCURRENT: store blocking chạy song song với ticker.
    t0 = time.perf_counter()
    _, ticks = await asyncio.gather(
        store.hybrid_search([0.0] * DIM, "q"), ticker()
    )
    t_concurrent = time.perf_counter() - t0

    # SERIAL baseline (cùng máy → tự hiệu chuẩn, miễn nhiễm granularity OS).
    t0 = time.perf_counter()
    await store.hybrid_search([0.0] * DIM, "q")
    await ticker()
    t_serial = time.perf_counter() - t0

    # Offload to_thread đúng => concurrent NHANH hơn rõ rệt serial (loop không bị chặn).
    assert ticks == 30, "ticker phải tiến triển trong lúc store blocking"
    assert t_concurrent < t_serial * 0.8, (
        f"event loop bị chặn? concurrent={t_concurrent:.2f}s không nhanh hơn serial={t_serial:.2f}s"
    )
    print(f"  B. to_thread offload: concurrent {t_concurrent:.2f}s << serial {t_serial:.2f}s "
          "(loop không bị blocking store chặn): OK")


# --------------------------------------------------------------------------- #
# C. Concurrent ingest (gather) vào store: không mất write, đúng số             #
# --------------------------------------------------------------------------- #
async def test_concurrent_ingest_no_lost_writes() -> None:
    if not _has_qdrant():
        print("  C. concurrent ingest: SKIP (chua cai qdrant-client cho store in_process)")
        return
    settings = HaystackSettings(embed_dimension=DIM)
    engine = HaystackRagEngine(
        settings=settings,
        embedder=ProviderEmbeddingService(OfflineProvider(DIM), dimension=DIM),
        vectors=_vectors(),
        reranker=SleepReranker(0.0),
        captioner=None,
    )

    N = 20
    counts = await asyncio.gather(*[engine.ingest(_doc(i)) for i in range(N)])
    assert all(c >= 1 for c in counts), "mọi ingest concurrent phải tạo chunk"

    total_docs = await _count_chunks(engine.vectors)
    assert total_docs == sum(counts), (
        f"concurrent ingest mất/đụng write: store={total_docs} != ingested={sum(counts)}"
    )

    # Re-ingest đồng thời cùng tập -> idempotent, KHÔNG nhân đôi.
    await asyncio.gather(*[engine.ingest(_doc(i)) for i in range(N)])
    assert await _count_chunks(engine.vectors) == total_docs, "concurrent re-ingest phải idempotent"

    res = await engine.search("word7", rerank_threshold=0.0)
    assert any(r.document_id == "d7" for r in res), "search sau concurrent ingest phải tìm đúng doc"
    print(f"  C. concurrent ingest: {N} doc, {total_docs} chunk, không mất write + idempotent: OK")


# --------------------------------------------------------------------------- #
# D. Order mapping: embed_batch giữ thứ tự == embed lẻ (idempotent response)    #
# --------------------------------------------------------------------------- #
async def test_batch_order_mapping() -> None:
    svc = ProviderEmbeddingService(OfflineProvider(DIM), dimension=DIM)
    texts = ["alpha mot", "beta hai", "gamma ba", "delta bon", "epsilon nam"]
    batch = await svc.embed_batch(texts)
    individually = await asyncio.gather(*[svc.embed(t) for t in texts])
    assert batch == individually, "embed_batch phải khớp thứ tự embed lẻ (request↔vector)"
    print("  D. order mapping: embed_batch giữ đúng thứ tự request↔vector: OK")


# --------------------------------------------------------------------------- #
# E. OpenAIProvider sort theo index dù API trả lộn xộn (response mapping)       #
# --------------------------------------------------------------------------- #
class _FakeEmbeddings:
    async def create(self, *, model, input, **kw):
        # Trả data ĐẢO NGƯỢC thứ tự nhưng có `index` đúng — provider phải sort lại.
        data = [SimpleNamespace(index=i, embedding=[float(i)]) for i in range(len(input))]
        return SimpleNamespace(data=list(reversed(data)))


class _FakeClient:
    embeddings = _FakeEmbeddings()


async def test_openai_provider_index_sort() -> None:
    s = AISettings(
        embed=CapabilityConfig(None, "sk-test", "m"),
        caption=CapabilityConfig(None, "sk-test", "m"),
        rerank=CapabilityConfig(None, "sk-test", "m"),
        embed_dimension=DIM,
    )
    provider = OpenAIProvider(s)
    # Inject fake client theo cache-key của capability embed (không gọi mạng).
    provider._clients[(s.embed.base_url, s.embed.api_key)] = _FakeClient()
    out = await provider.embed(["a", "b", "c", "d"])
    assert out == [[0.0], [1.0], [2.0], [3.0]], "phải sort theo index dù API trả lộn xộn"
    print("  E. OpenAIProvider: sort embedding theo index (response mapping): OK")


# --------------------------------------------------------------------------- #
# F. retry_async: retry transient rồi thành công; hết lượt thì raise           #
# --------------------------------------------------------------------------- #
async def test_retry_policy() -> None:
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient 429")
        return "ok"

    out = await retry_async(flaky, max_retries=5, base_delay=0.001)
    assert out == "ok" and calls["n"] == 3, "phải retry tới khi thành công"

    hits = {"n": 0}

    async def always():
        hits["n"] += 1
        raise RuntimeError("permanent")

    raised = False
    try:
        await retry_async(always, max_retries=2, base_delay=0.001)
    except RuntimeError:
        raised = True
    assert raised, "hết lượt retry phải raise (không nuốt lỗi)"
    assert hits["n"] == 3, f"phải gọi 1 lần + 2 retry = 3, thực tế {hits['n']}"
    print("  F. retry_async: backoff retry transient + raise khi hết lượt: OK")


async def run() -> None:
    await test_io_concurrency_overlap()
    await test_blocking_offload_keeps_loop_alive()
    await test_concurrent_ingest_no_lost_writes()
    await test_batch_order_mapping()
    await test_openai_provider_index_sort()
    await test_retry_policy()
    print("OK - async self-tests PASS")


if __name__ == "__main__":
    asyncio.run(run())
