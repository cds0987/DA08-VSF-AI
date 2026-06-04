# GAP v4 - rag-service: MVP in-memory verify + suite xanh 100%

Scope: chỉ `src/rag-service`.
Grounding: `docs/gap.md`, `docs/gap-v2.md`, `docs/gap3.md`, `docs/handoff/CONSTRAINTS.md`.
Updated: 2026-06-04 · Nhánh: `nguyendev`

## Mục tiêu pass này

Chốt MVP tối thiểu = **single-replica + inline-markdown ingest + Qdrant in-memory**
(chưa serve vector ra ngoài), và làm test suite xanh 100% trên môi trường đã cài đủ
dependencies.

## Trạng thái

| ID | Khu vực | Trước | Sau |
|---|---|---|---|
| V4-1 | Dependencies cài đủ | Môi trường local thiếu `qdrant-client`/`psycopg`/`pymupdf` ⇒ 7 test đỏ do ImportError | Đã `pip install -r requirements.txt` thành công trên Python 3.14.5 (wheel đủ); các test phụ thuộc backend chạy lại |
| V4-2 | Qdrant in-memory cho MVP | Chưa được verify end-to-end ngoài unit/stub | Verify thật: inline markdown → engine (offline embed) → Qdrant `:memory:` (in_process) → search trả kết quả có lineage + correlation_id. **Không cần code mới** — để trống `VECTOR_DB_URL` là đủ |
| V4-3 | SQLite tz fail (gap3 note) | `test_..._renews_processing_claim` đỏ: `can't compare offset-naive and offset-aware datetimes` (SQLite trả naive) | Closed: adapter chuẩn hóa datetime đọc ra thành aware-UTC (`_as_aware_utc`) ⇒ domain nhất quán giữa SQLite/Postgres, chặn cả lớp bug so sánh naive/aware ở Python |
| V4-4 | E2E test cho luồng MVP | Chỉ có test stub ở use-case/router; engine thật + Qdrant chỉ trong `core_engine/tests` (search contract) | Thêm `tests/e2e/test_inmemory_ingest_search.py`: engine/embedder/vectorstore đều thật, chạy trong CI không cần OpenAI/Postgres/Qdrant remote |

**Kết quả suite:** `63 passed, 1 skipped, 0 failed`. Skip duy nhất là
`test_qdrant_remote_contract` (opt-in, cần `QDRANT_URL`).

## Chi tiết

### V4-1. Cài dependencies
- `requirements.txt` resolve sạch trên Python 3.14.5; có wheel cho `qdrant-client==1.18.0`,
  `pymupdf==1.27.2.3`, `psycopg[binary]==3.3.4`, `markitdown[pptx,xls,xlsx]==0.1.6`,
  `openai==1.59.6`.

### V4-2. Qdrant in-memory đã chạy
- `VectorStoreConfig` suy `deployment` từ `url`: rỗng ⇒ `in_process` ⇒
  `QdrantInProcessProvider` dùng `:memory:` (RAM, không persist).
- Verify bằng `tests/e2e/test_inmemory_ingest_search.py` và script tay
  `.tmp/demo_inmemory_ingest.py` (untracked).
- **Cảnh báo vận hành:** `:memory:` mất sạch khi restart ⇒ chỉ dev/MVP-thử. Production
  fail-closed cố tình raise nếu vector là `in_process` (runtime.py). Lên durable chỉ cần
  đặt `VECTOR_DB_URL=http://qdrant:6333`, **không đổi code**.

### V4-3. Datetime aware-UTC ở metadata adapter
- `PostgresDocumentRepository._to_domain/_to_job/_to_job_log` bọc các trường thời gian
  bằng `_as_aware_utc()`. SQLite (test) trả naive → coi là UTC; Postgres `timestamptz`
  vốn aware nên không đổi hành vi.

### V4-4. E2E test mới
- 3 case: (1) inline markdown ingest→search có đủ contract field; (2) re-ingest tài liệu
  ngắn hơn prune chunk cũ trong Qdrant memory; (3) search collection rỗng trả `[]`.
- Offline provider ⇒ `caption=False` + `rerank_threshold=0.0` (kiểm plumbing, không kiểm
  chất lượng — chất lượng cần provider thật).

## Cách chạy MVP với Qdrant in-memory

```
APP_ENV=development        # KHÔNG production: fail-closed chặn in_process (không durable)
VECTOR_DB_URL=             # rỗng => Qdrant embedded :memory:
VECTOR_DB_PROVIDER=qdrant
EMBED_DIMENSION=256        # khớp OfflineProvider; provider thật thì theo model
# bỏ OPENAI_API_KEY => OfflineProvider ; bỏ DATABASE_URL => InMemoryDocumentRepository
python -m uvicorn app.interfaces.api.main:app --port 8000
```

## Còn lại (không chặn MVP in-memory)

- Lên durable: Qdrant remote + Postgres + provider AI thật (đổi env, không đổi code).
- Object storage cho artifact/file nguồn — chỉ cần khi multi-replica hoặc bật file ingest
  (xem gap.md #17, gap-v2 P2).
- Auth ở edge giao gateway; rate limiter hiện per-process (gap.md 🟡).
- Observability (metrics/tracing) và eval-CI provider thật vẫn là follow-up.

## References
- [gap.md](./gap.md) · [gap-v2.md](./gap-v2.md) · [gap3.md](./gap3.md)
- `tests/e2e/test_inmemory_ingest_search.py`
- `app/infrastructure/db/postgres_document_repository.py` (`_as_aware_utc`)
