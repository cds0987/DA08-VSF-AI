#!/usr/bin/env python3
"""
CI integration THUẦN rag-worker: chạy ĐÚNG luồng ingest của rag-worker với
`IngestTracer` + Langfuse client THẬT, các "service" ngoài (embedder/captioner/
vectors) là stub nhưng MÔ PHỎNG ĐÚNG luồng data. Verify qua Langfuse public API:

  - 1 doc THÀNH CÔNG  -> trace `doc-ingest` có đủ span stage + status=SUCCESS.
  - 2 doc LỖI stage   -> trace status=FAILED + observation `level=ERROR` đúng stage
                         (embed, qdrant-write). Đây là cái bảo đảm lỗi KHÔNG lọt
                         khi vào production: "biết crash ở đâu" được verify thật.

Fail-closed: sai bất kỳ assert nào -> exit != 0 (giống các validate CI khác).
Workflow XÓA trace test ở tầng Postgres theo session_id prefix 'raglf-ci-'
(Langfuse v2 không có public API xóa trace).

ENV: LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

# Cho phép `from app...` / `from core_engine...` khi chạy script trực tiếp.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from app.infrastructure.observability.langfuse_tracer import IngestTracer  # noqa: E402
from core_engine.config import HaystackSettings  # noqa: E402
from core_engine.engine import HaystackRagEngine, IngestInput  # noqa: E402

HOST = os.environ["LANGFUSE_HOST"].rstrip("/")
AUTH = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
SESSION_PREFIX = "raglf-ci-"
MARKDOWN = "# Title\none two three four five six seven eight nine ten eleven twelve"


# ── Stub "service" ngoài: đúng interface, mô phỏng đúng luồng data ──────────────
class _Provider:
    @staticmethod
    def cap(capability: str):
        return type("Cfg", (), {"model": f"{capability}-model"})()


class StubEmbedder:
    def __init__(self) -> None:
        self._provider = _Provider()

    async def embed(self, text: str):
        return [0.1, 0.2, 0.3]

    async def embed_batch(self, texts: list[str]):
        return [[0.1, 0.2, 0.3] for _ in texts]


class StubVectors:
    def __init__(self) -> None:
        self.config = type("Cfg", (), {"index_id": lambda self: "rag_chatbot__te3s__d1536"})()

    async def upsert_many(self, records):
        return None

    async def list_chunk_ids_by_document(self, document_id):
        return []

    async def delete_many(self, chunk_ids):
        return None

    async def delete_by_document(self, document_id):
        return None


class StubCaptioner:
    def __init__(self) -> None:
        self._provider = _Provider()

    async def caption_with_metadata(self, text: str):
        return type("CaptionResult", (), {"text": f"caption:{text[:5]}", "used_fallback": False})()


class BoomEmbedder(StubEmbedder):
    async def embed_batch(self, texts: list[str]):
        raise RuntimeError("embed boom (simulated model/API failure)")


class BoomVectors(StubVectors):
    async def upsert_many(self, records):
        raise RuntimeError("qdrant boom (simulated write failure)")


def _settings() -> HaystackSettings:
    return HaystackSettings(
        embed_dimension=3, parent_max_words=100, child_max_words=4, child_overlap_words=1
    )


async def _run_flow(tracer: IngestTracer, doc_id: str, *, embedder, vectors, fail_stage):
    """Mô phỏng đúng orchestration rag-worker: start_job -> engine.ingest -> finish_job."""
    engine = HaystackRagEngine(
        settings=_settings(),
        embedder=embedder,
        vectors=vectors,
        captioner=StubCaptioner(),
        tracer=tracer,
    )
    meta = {
        "job_id": doc_id,
        "attempt": 0,
        "uri": f"inline://{doc_id}",
        "mime": "md",
        "collection": "rag_chatbot__te3s__d1536",
    }
    trace = tracer.start_job(doc_id, meta)
    trace_id = trace.trace.id  # sample_rate=1.0 -> luôn có trace object
    try:
        n = await engine.ingest(
            IngestInput(
                document_id=doc_id,
                document_name="Doc",
                file_type="md",
                markdown=MARKDOWN,
                trace_handle=trace,
            )
        )
        await tracer.finish_job(trace, "SUCCESS", {"total_chunks": n})
        return trace_id, "SUCCESS"
    except Exception as exc:  # noqa: BLE001 — mô phỏng đường FAILED của use_case
        await tracer.finish_job(trace, "FAILED", {"stage": fail_stage, "error": str(exc)[:200]})
        return trace_id, "FAILED"


def _get_trace(trace_id: str) -> dict | None:
    for _ in range(15):
        r = requests.get(f"{HOST}/api/public/traces/{trace_id}", auth=AUTH, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if data.get("observations"):
                return data
        time.sleep(2)
    # lần cuối: trả kể cả khi chưa có observations để in chẩn đoán
    r = requests.get(f"{HOST}/api/public/traces/{trace_id}", auth=AUTH, timeout=15)
    return r.json() if r.status_code == 200 else None


def _fail(msg: str) -> None:
    print(f"  FAIL: {msg}", flush=True)
    sys.exit(1)


def _verify_success(trace_id: str) -> None:
    data = _get_trace(trace_id)
    if data is None:
        _fail(f"trace success {trace_id} không hiện trên Langfuse")
    names = {o.get("name") for o in data.get("observations", [])}
    print(f"  success trace observations = {sorted(n for n in names if n)}")
    for stage in ("chunk", "caption", "embed", "qdrant-write"):
        if stage not in names:
            _fail(f"thiếu span '{stage}' trong trace success (luồng stage không lên Langfuse)")
    status = (data.get("output") or {}).get("status")
    if status != "SUCCESS":
        _fail(f"trace success có output.status={status!r}, mong đợi SUCCESS")
    print("  OK: trace SUCCESS đủ span stage + status=SUCCESS")


def _verify_failed(trace_id: str, stage: str) -> None:
    data = _get_trace(trace_id)
    if data is None:
        _fail(f"trace failed {trace_id} không hiện trên Langfuse")
    status = (data.get("output") or {}).get("status")
    if status != "FAILED":
        _fail(f"trace failed[{stage}] có output.status={status!r}, mong đợi FAILED")
    err_spans = [
        o.get("name")
        for o in data.get("observations", [])
        if str(o.get("level", "")).upper() == "ERROR"
    ]
    print(f"  failed[{stage}] ERROR observations = {err_spans}")
    if stage not in err_spans:
        _fail(f"không có observation level=ERROR ở stage '{stage}' (lỗi sẽ LỌT khi vào prod)")
    print(f"  OK: trace FAILED + span '{stage}' level=ERROR (biết crash ở đâu)")


async def _amain() -> None:
    from langfuse import Langfuse  # import trễ để lỗi thiếu dep rõ ràng

    client = Langfuse(public_key=AUTH[0], secret_key=AUTH[1], host=HOST)
    tracer = IngestTracer(client, sample_rate=1.0, trace_on_error=True)

    run = os.environ.get("GITHUB_RUN_ID", str(int(time.time())))
    ok_id, ok_status = await _run_flow(
        tracer, f"{SESSION_PREFIX}{run}-ok", embedder=StubEmbedder(), vectors=StubVectors(),
        fail_stage=None,
    )
    emb_id, emb_status = await _run_flow(
        tracer, f"{SESSION_PREFIX}{run}-embedfail", embedder=BoomEmbedder(), vectors=StubVectors(),
        fail_stage="embed",
    )
    qdr_id, qdr_status = await _run_flow(
        tracer, f"{SESSION_PREFIX}{run}-qdrantfail", embedder=StubEmbedder(), vectors=BoomVectors(),
        fail_stage="qdrant-write",
    )
    client.flush()

    print(f"ingest xong: ok={ok_status} embed={emb_status} qdrant={qdr_status}", flush=True)
    if ok_status != "SUCCESS":
        _fail("doc tốt KHÔNG SUCCESS (luồng ingest cơ bản gãy)")
    if emb_status != "FAILED" or qdr_status != "FAILED":
        _fail("doc lỗi KHÔNG raise -> FAILED (lỗi stage bị nuốt)")

    print("verify trên Langfuse:", flush=True)
    _verify_success(ok_id)
    _verify_failed(emb_id, "embed")
    _verify_failed(qdr_id, "qdrant-write")
    print("PASS: rag-worker chạy với Langfuse + bắt được lỗi từng stage.", flush=True)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
