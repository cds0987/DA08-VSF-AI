# GAP v7 — rag-worker: captioner logic, enqueue atomicity & worker throughput

Scope: `src/rag-worker` — engine ingest, job queue, DB repository, S3 parser, chunker.
Grounding: deep code review tại `nguyendev` HEAD (2026-06-07) — đọc từ entrypoint → worker
→ engine → DB adapter → NATS consumer → test suite.
Status: **CLOSED** (2026-06-07) — G7-1..G7-18 đã fix; xem mục *Tổng kết triển khai* cuối file.

---

## Điểm mạnh giữ nguyên (không regress khi fix)

- **Optimistic-lock claim**: SELECT + conditional UPDATE `rowcount == 1` — concurrent workers
  không double-claim (đã verify từ G6).
- **Heartbeat + stale-reaper**: `renew_claim` + `mark_stale_jobs` — worker chết được
  recover tự động không cần can thiệp.
- **NATS term/nak phân biệt**: `BadPayloadError → term`, transient → nak — không retry
  vô hạn payload poison.
- **S3 download 5 lớp guard**: HEAD size, stream-to-disk, byte counter, semaphore, finally
  cleanup — không OOM/đầy đĩa.
- **Production fail-closed startup**: AI/DB/vector sai cấu hình → hard raise trước khi
  nhận traffic.
- **Stale chunk pruning**: `engine.py:129-131` — re-ingest cùng document xóa chunk cũ, không
  tích luỹ orphan vector.

---

## Gaps đã xác minh

| ID | Mức | Vấn đề | File / dòng | Trạng thái |
|----|-----|---------|-------------|------------|
| G7-1 | **P0** | Captioner bật → chỉ 1 chunk/section, child windows bị drop | `engine.py:76-85` | OPEN |
| G7-2 | **P0** | `create(doc)` + `enqueue(job)` không atomic — orphan Document khi call thứ 2 fail | `ingest_document_use_case.py:73-96` | OPEN |
| G7-3 | **P0** | `session.merge()` upsert Document — NATS redeliver sau COMPLETED reset về QUEUED | `postgres_document_repository.py:88` | OPEN |
| G7-4 | **P1** | Không có timeout bao `engine.ingest()` — worker block indefinitely | `ingest_document_use_case.py:129` | OPEN |
| G7-5 | **P1** | Captioning tuần tự — N LLM calls sequential trong hot path | `engine.py:77` | OPEN |
| G7-6 | **P1** | S3 client cache không thread-safe — lazy init trong `to_thread` | `s3_parser.py:183-186` | OPEN |
| G7-7 | **P1** | `_fail_jobs_exceeding_max_attempts` chạy mỗi `claim_next_pending` | `postgres_document_repository.py:296-301` | OPEN |
| G7-8 | **P1** | `doc.status` publish fail swallowed — downstream không biết job xong | `ingest_consumer.py:191-196` | CLOSED via doc.status outbox sweep |
| G7-9 | **P2** | `SELECT` không dùng `FOR UPDATE SKIP LOCKED` — N workers wasted round-trips | `postgres_document_repository.py:302-313` | OPEN |
| G7-10 | **P2** | `_cap_words` cắt giữa câu — embedding chunk cụt | `sections.py:72-76` | OPEN |
| G7-11 | **P2** | `page_number` trong vector payload là section index, không phải page PDF | `sections.py:47-49` | OPEN |
| G7-12 | **P2** | Toàn bộ ảnh PDF buffer RAM trước OCR — OOM risk với doc lớn | `local_parser.py:394-403` | OPEN |

---

## G7-1 — Captioner bật → 1 chunk/section (P0)

**Vấn đề:**
`engine.py:76-85` — khi `self.captioner is not None`, engine tạo đúng 1 unit
`(parent_id::c0, caption, caption, parent_text)` bất kể section dài bao nhiêu.
`section.children` (sliding windows từ `SectionChunker`) bị bỏ qua hoàn toàn.

```python
# HIỆN TẠI — BUG
if self.captioner is not None:
    caption = await self.captioner.caption(section.parent_text)
    units = [(f"{parent_id}::c0", caption, caption, section.parent_text)]
else:
    units = [(f"{parent_id}::c{i}", child, child, child)
             for i, child in enumerate(section.children)]
```

Section 300 words với `CHILD_MAX_WORDS=90` nên sinh 4 children windows.
Khi captioner bật → chỉ 1 embedding. Câu hỏi về đoạn cuối section không khớp.

**Fix:**
```python
if self.captioner is not None:
    caption = await self.captioner.caption(section.parent_text)
    # Giữ child windows để embed granular; caption dùng làm child_text (search text)
    # còn bm25_text = child gốc để BM25 vẫn thấy từ khoá thật.
    units = [
        (f"{parent_id}::c{i}", caption, caption, child)
        for i, child in enumerate(section.children)
    ]
else:
    units = [
        (f"{parent_id}::c{i}", child, child, child)
        for i, child in enumerate(section.children)
    ]
```

**Semantic**: `to_embed = caption` (embedding chạy trên caption đại diện nghĩa section),
`bm25_text = child` (BM25 chạy trên text gốc), `parent_text` không đổi.
Số chunk = số children — nhất quán với không-captioner.

---

## G7-2 — `create(doc)` + `enqueue(job)` không atomic (P0)

**Vấn đề:**
`ingest_document_use_case.py:73-96` thực hiện 2 DB call riêng biệt:

```python
await self._documents.create(Document(..., status=QUEUED))  # DB call 1
# --- window: nếu crash/timeout ở đây → Document tồn tại, không có job ---
await self._jobs.enqueue(job)                                # DB call 2
```

Nếu call 2 fail (DB timeout, constraint, network), Document bị stuck ở QUEUED
vĩnh viễn — không có IngestJob nào claim nó. Stale reaper không biết Document
mồ côi này.

**Fix ngắn hạn** (không cần thay đổi schema): Cleanup Document nếu enqueue fail.

```python
await self._documents.create(Document(..., status=QUEUED))
try:
    await self._jobs.enqueue(job)
except Exception:
    with contextlib.suppress(Exception):
        await self._documents.delete(document_id)
    raise
```

**Fix dài hạn**: Thêm `create_document_with_job(doc, job)` trong repo layer dùng
một transaction SQLAlchemy (cả 2 INSERT trong cùng session → commit 1 lần).

---

## G7-3 — `session.merge()` overwrite Document (P0)

**Vấn đề:**
`postgres_document_repository.py:88` — `_create_sync` dùng `session.merge(record)`.
`merge()` = INSERT hoặc UPDATE (upsert). Nếu `document_id` đã tồn tại (dù status
COMPLETED), nó overwrite toàn bộ row về trạng thái mới (QUEUED, chunk_count=None).

Scenario: NATS redeliver `doc.ingest` sau job COMPLETED
→ `find_active_job()` trả None (không có active job)
→ `create()` gọi `merge()` → Document reset QUEUED
→ job mới tạo ra → re-embed không cần thiết.

**Fix:**
```python
def _create_sync(self, document: Document) -> Document:
    with self._session() as session:
        record = DocumentRecord(...)
        session.add(record)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            existing = session.get(DocumentRecord, document.id)
            if existing is None:
                raise
            return self._to_domain(existing)
        return self._to_domain(record)
```

Pattern nhất quán với `_enqueue_sync` (đã xử lý IntegrityError đúng cách).

Nếu muốn cho phép re-ingest chủ động (không phải redelivery), caller phải xóa
document cũ trước (`delete()`) rồi mới `create()` — explicit intent, không
implicit overwrite.

---

## G7-4 — Không có timeout bao `engine.ingest()` (P1)

**Vấn đề:**
`ingest_document_use_case.py:129` — không có `asyncio.wait_for`:

```python
chunk_count = await self._engine.ingest(IngestInput(...))
```

Với OCR trên 25 trang × ~2s/trang vision call = ~50s tối thiểu.
Nếu OpenAI timeout không config đúng hoặc embed API treo, worker block vô thời hạn.
Heartbeat task vẫn renew claim → job không bao giờ bị stale → worker bị chiếm.

**Fix:**
```python
INGEST_JOB_TIMEOUT_SECONDS = float(os.getenv("INGEST_JOB_TIMEOUT_SECONDS", "600"))

chunk_count = await asyncio.wait_for(
    self._engine.ingest(IngestInput(...)),
    timeout=INGEST_JOB_TIMEOUT_SECONDS,
)
```

`asyncio.TimeoutError` sẽ propagate lên except block đã có → job FAILED đúng cách.
Validate trong `validate_runtime_settings()`: `INGEST_JOB_TIMEOUT_SECONDS > 0`.

---

## G7-5 — Captioning tuần tự trong hot path (P1)

**Vấn đề:**
`engine.py:77` trong for loop — `await self.captioner.caption(section.parent_text)`
chạy tuần tự. Doc 20 sections × 500ms/call = 10s thêm vào latency ingest.

**Fix:**
```python
if self.captioner is not None:
    captions = await asyncio.gather(
        *[self.captioner.caption(s.parent_text) for s in sections]
    )
```

Nếu cần kiểm soát rate limit OpenAI, dùng semaphore:
```python
_sem = asyncio.Semaphore(5)
async def _caption(text):
    async with _sem:
        return await self.captioner.caption(text)
captions = await asyncio.gather(*[_caption(s.parent_text) for s in sections])
```

---

## G7-6 — S3 client không thread-safe (P1)

**Vấn đề:**
`s3_parser.py:183-186` — `_get_client()` lazy-init với check `if self._client is None`.
`parse()` gọi `asyncio.to_thread(self._download_guarded, ...)` — nếu N jobs S3
start gần như cùng lúc, N thread đều thấy `self._client is None` trước khi thread
đầu tiên gán xong → tạo N boto3 client song song (connection pool leak).

```python
def _get_client(self) -> Any:
    if self._client is None:          # race: N threads cùng thấy None
        self._client = self._client_factory()
    return self._client
```

**Fix:** Move init vào `__init__`:
```python
def __init__(self, ...):
    ...
    self._client = self._client_factory()   # eager, single init
```

Hoặc dùng `threading.Lock` nếu muốn giữ lazy:
```python
self._client_lock = threading.Lock()

def _get_client(self):
    with self._client_lock:
        if self._client is None:
            self._client = self._client_factory()
    return self._client
```

---

## G7-7 — `_fail_jobs_exceeding_max_attempts` trong mỗi claim poll (P1)

**Vấn đề:**
`postgres_document_repository.py:296-301` — `_claim_next_pending_sync` gọi
`_fail_jobs_exceeding_max_attempts` như side-effect mỗi lần poll.

Với `INGEST_WORKER_COUNT=3` và `INGEST_WORKER_POLL_INTERVAL_SECONDS=0.5`,
khi queue trống: 3 workers × 2/giây = **6 SELECT/giây** trên toàn bảng
`ingest_jobs` để tìm jobs vượt max_attempts — dù không có job nào.

**Fix:** Xóa lời gọi khỏi `_claim_next_pending_sync`. Chuyển vào
`_mark_stale_jobs_sync` (đã chạy mỗi `reaper_interval_seconds`, mặc định 30s).

```python
def _mark_stale_jobs_sync(self, stale_before: datetime) -> int:
    with self._session() as session:
        now = datetime.now(UTC)
        # Terminal jobs vượt max_attempts (cả PROCESSING và STALE)
        failed_count = self._fail_jobs_exceeding_max_attempts(
            session,
            stale_before=stale_before,
            statuses=(IngestJobStatus.PROCESSING.value, IngestJobStatus.STALE.value),
            now=now,
        )
        # Pending/STALE chưa vượt limit → mark STALE để retry
        ...
```

Thêm cả `PENDING` vào statuses để bắt job pending nhiều lần không được claim.

---

## G7-8 — `doc.status` publish fire-and-forget (P1)

**Vấn đề:**
`ingest_consumer.py:191-196` — `DocStatusPublisher.publish_for_job` swallow exception:

```python
except Exception as exc:
    self._logger.warning("doc_status_publish_failed ...")
    # không có retry, không có lưu lại
```

Job đã COMPLETED trong DB nhưng NATS publish fail → document-service không biết
→ document bị stuck "processing" ở phía client cho đến khi timeout/poll.

**Fix ngắn hạn:** Thêm retry với exponential backoff trong publisher:
```python
for attempt in range(3):
    try:
        await self._broker.publish_json(self._subject, message)
        return
    except Exception:
        if attempt == 2:
            self._logger.error("doc_status_publish_failed_terminal ...")
        await asyncio.sleep(0.5 * (2 ** attempt))
```

**Fix đã chọn (outbox-lite):** thêm cờ bền `status_published_at` trên `ingest_jobs`.
Worker publish inline như cũ; publish OK thì mark timestamp. Publish trượt hoặc job terminal
được set ở reaper/max-attempts thì background sweep quét mọi job `COMPLETED/FAILED` chưa mark
và publish lại. Cơ chế này đảm bảo **at-least-once** qua restart mà không cần bảng outbox riêng.

---

## G7-9 — Không dùng `SELECT FOR UPDATE SKIP LOCKED` (P2)

**Vấn đề:**
`postgres_document_repository.py:302-313` — pattern SELECT rồi UPDATE conditional:

```python
record = session.execute(stmt).scalars().first()   # SELECT không lock
...
result = session.execute(update(...).where(id == record.id, status in [...]))
if result.rowcount != 1:
    return None   # worker khác đã claim → wasted round-trip
```

Với N workers, N-1 workers mỗi chu kỳ tốn 1 SELECT + 1 UPDATE miss.

**Fix:**
```python
stmt = (
    select(IngestJobRecord)
    .where(IngestJobRecord.status.in_([...]))
    .order_by(...)
    .limit(1)
    .with_for_update(skip_locked=True)   # thêm dòng này
)
```

`SKIP LOCKED` bỏ qua row đang bị lock bởi worker khác — mỗi worker select
record khác nhau ngay lập tức, không wasted round-trip.

---

## G7-10 — `_cap_words` cắt giữa câu (P2)

**Vấn đề:**
`sections.py:72-76` — split thuần túy theo word count:

```python
return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)]
```

Section 250 words, max=220 → đoạn thứ 2 chỉ có 30 words đầu câu tiếp theo bị cắt
cụt → embedding nhiễu, context không đủ.

**Fix nhẹ:** Split tại sentence boundary (`[.!?]`) trước, gom câu cho đến gần
max_words rồi mới cut:

```python
import re

def _cap_words_sentence_aware(text: str, max_words: int) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks, current, count = [], [], 0
    for sent in sentences:
        wc = len(sent.split())
        if count + wc > max_words and current:
            chunks.append(" ".join(current))
            current, count = [], 0
        current.append(sent)
        count += wc
    if current:
        chunks.append(" ".join(current))
    return chunks or [text]
```

---

## G7-11 — `page_number` là section index, không phải page PDF (P2)

**Vấn đề:**
`sections.py:21-22` — field `page_number` trong `Section` được comment là
*"placeholder: thứ tự section"*. Biến `page` trong `split_sections` tăng theo
số section, không theo trang PDF thật.

Vector payload `page_number` gửi về query-service sẽ hiển thị sai cho người dùng
(vd "trang 5" nhưng thực ra là section 5 nằm ở trang 2).

**Fix:** Parser (pymupdf) đã biết page number thật (`fitz.Page`). Truyền thông tin
này vào `Section` qua `ParsedArtifact`:

1. `ParsedArtifact.markdown` thêm page marker (vd `<!-- page:3 -->`) hoặc
2. `ParsedArtifact` thêm field `page_map: list[tuple[int, int]]` (char_offset → page).

`split_sections` lookup page map để gán `page_number` đúng.

Đây là refactor lớn; trước mắt đổi tên field thành `section_index` để không mislead.

---

## G7-12 — Buffer toàn bộ ảnh PDF trong RAM trước OCR (P2)

**Vấn đề:**
`local_parser.py:236-256` — pymupdf reader thu thập tất cả `_Page` (kể cả ảnh
rasterized) vào `_ParseStep.pages` list trước khi trả về. Sau đó `parse()` lặp qua
từng page và gọi OCR.

Doc 25 trang scan, scale=2.0, mỗi trang ~8MB raw PNG → `_ParseStep` giữ
~200MB ảnh trong RAM cho đến khi OCR xong trang cuối cùng.

**Fix:** Refactor `parse()` thành streaming generator — yield từng page, OCR ngay,
clear image bytes sau khi extract:

```python
async def parse(self, ...) -> ParsedArtifact:
    ...
    parts = []
    for page in step.pages:
        ocr_text = ""
        if page.images:
            ocr_text = await self._image_text_extractor.extract(page.images)
            page.images.clear()   # giải phóng RAM ngay sau OCR page này
        ...
```

`page.images.clear()` đã đủ nếu không có reference nào khác giữ list — không cần
thay đổi interface.

---

## Missing tests cần bổ sung

| Test | File đề xuất | Covers |
|------|-------------|--------|
| `split_sections` với captioner — verify chunk count = len(children) | `tests/core_engine/test_engine_ingest.py` | G7-1 |
| `_cap_words` cắt đúng, không cụt câu | `tests/core_engine/test_chunker.py` | G7-10 |
| `create()` duplicate document_id → return existing, không overwrite | `tests/infrastructure/db/test_postgres_document_repository.py` | G7-3 |
| `enqueue()` fail sau `create()` → Document được cleanup | `tests/application/ingestion/test_ingest_document_use_case.py` | G7-2 |
| `engine.ingest()` timeout → job FAILED | `tests/application/ingestion/test_ingest_document_use_case.py` | G7-4 |
| NATS redeliver sau COMPLETED → no duplicate job | `tests/interfaces/nats/test_ingest_consumer.py` | G7-3 |
| Concurrent workers claim same job → chỉ 1 thắng (Postgres) | `tests/infrastructure/db/test_postgres_document_repository.py` | G7-9 |
| `_fail_jobs_exceeding_max_attempts` không chạy trong claim khi tách | `tests/infrastructure/db/test_postgres_document_repository.py` | G7-7 |

---

## Thứ tự fix được khuyến nghị

```
G7-1  (captioner chunk bug)    → sửa + test → verify chunk_count tăng
G7-3  (session.merge → add)    → sửa + test → verify re-ingest idempotent
G7-2  (atomic enqueue)         → sửa + test → verify no orphan document
G7-4  (ingest timeout)         → sửa + validate INGEST_JOB_TIMEOUT_SECONDS
G7-6  (S3 client thread-safe)  → sửa __init__
G7-5  (captioning parallel)    → sửa asyncio.gather + semaphore
G7-7  (fail_exceeding tách)    → sửa + chuyển vào stale reaper
G7-8  (doc.status outbox-lite) → sửa publisher/repo/runtime + test
G7-9  (SKIP LOCKED)            → sửa query
G7-10 (cap_words sentence)     → sửa + test
G7-11 (page_number rename)     → đổi tên field trước, fix sau
G7-12 (RAM streaming OCR)      → images.clear() sau extract
```

---

# Bổ sung — review lần 2 (2026-06-07)

> Verify lại toàn bộ G7-1..G7-12 trên `nguyendev` HEAD: **tất cả vẫn OPEN và mô tả đúng
> bản chất**. Một số gap dưới đây gap7 bản đầu bỏ sót — bổ sung kèm grounding line thực tế.

## ⚠️ Sửa path — file KHÔNG nằm ở gốc `src/rag-worker`

Bản gap7 trên ghi `engine.py`, `sections.py`, `core_engine` rời rạc. Path thực tế:

| gap7 ghi | Path thật |
|----------|-----------|
| `engine.py` | `core_engine/engine.py` |
| `sections.py` | `core_engine/chunking/sections.py` |
| `s3_parser.py` | `app/infrastructure/external/s3_parser.py` |
| `local_parser.py` | `app/infrastructure/external/local_parser.py` |
| `ingest_document_use_case.py` | `app/application/use_cases/ingestion/ingest_document_use_case.py` |
| `postgres_document_repository.py` | `app/infrastructure/db/postgres_document_repository.py` |
| `ingest_consumer.py` | `app/interfaces/nats/ingest_consumer.py` |

Line numbers trong G7-1..G7-12 khớp ±2 dòng với HEAD hiện tại. G7-6 đã verify đúng tại
`s3_parser.py:183-186` (lazy `_get_client`, `self._client=None` trong `__init__`).

---

## G7-13 — Re-deliver sau COMPLETED VẪN re-ingest (fix G7-3 chưa đủ) (P0)

**Vấn đề:** Fix G7-3 (đổi `merge` → `add`+catch IntegrityError) chỉ chặn việc **reset row
Document**. Nó KHÔNG chặn việc tạo job mới + re-embed. Lý do:
`ingest_document_use_case.py:59` — `find_active_job()` chỉ tìm status trong
`_ACTIVE_INGEST_JOB_STATUSES = (PENDING, PROCESSING, STALE)`. Job COMPLETED là **terminal**,
không nằm trong set này → trả `None` → enqueue đi tiếp tạo `IngestJob` mới → worker
re-parse S3 + re-embed toàn bộ. (Idempotent về vector nhờ upsert cùng `chunk_id`, nhưng
tốn full chi phí parse+OCR+embed mỗi lần NATS redeliver.)

**Fix:** trong `enqueue()`, sau khi `find_active_job` trả None, kiểm tra document đã
COMPLETED chưa; nếu rồi và caller không yêu cầu re-ingest tường minh → skip.

```python
existing = await self._jobs.find_active_job(document_id)
if existing is not None:
    return existing
doc = await self._documents.get_by_id(document_id)
if doc is not None and doc.status is DocumentStatus.COMPLETED:
    log_event(..., "ingest_enqueue_skipped_completed", ...)
    return  # hoặc trả job COMPLETED gần nhất
```

Re-ingest chủ động (BE đổi nội dung file) phải đi qua `delete()` trước → explicit intent,
nhất quán với note G7-3.

## G7-14 — `embed_batch` gửi TẤT CẢ chunk trong 1 request — fail doc lớn (P1)

**Vấn đề:** `engine.py:121` — `vectors = await self.embedder.embed_batch(embed_texts)` đẩy
**toàn bộ** embed_texts một lần. `ProviderEmbeddingService.embed_batch`
(`embedding/service.py:27-30`) gọi thẳng `provider.embed(texts)` không chia batch.
Doc dài (vài trăm section × children) → 1 request OpenAI embeddings vượt giới hạn inputs/token
per request → API 400 → cả ingest FAILED (không chunk nào được ghi).

**Fix:** chia batch theo `EMBED_BATCH_SIZE` (vd 100) trong `embed_batch`, gather tuần tự
hoặc giới hạn concurrency:

```python
async def embed_batch(self, texts):
    if not texts:
        return []
    out: list[list[float]] = []
    for i in range(0, len(texts), self._batch_size):
        out.extend(await self._provider.embed(texts[i:i+self._batch_size], dimension=self._dim))
    return out
```

## G7-15 — `doc.access delete` đua với ingest đang chạy → vector "sống lại" (P1)

**Vấn đề:** `DocAccessDeleteConsumer.handle` (`ingest_consumer.py:150`) gọi
`ingest.delete()` → xóa Document + ingest_jobs + vector. Nhưng nếu một worker đang chạy
`process_next_job` cho cùng `document_id` (đã claim job trong RAM, đang ở bước
`engine.ingest` → `upsert_many`), thứ tự có thể là: delete xóa vector → worker upsert lại →
**vector mồ côi của document đã bị xóa** tồn tại vĩnh viễn trong Qdrant, query-service vẫn
trả về. `delete()` xóa được row `ingest_jobs` nhưng không hủy được claim in-memory.

**Fix:** sau `upsert_many`/`complete_job`, kiểm tra document còn tồn tại không (đã bị delete
chưa) trong cùng transaction completion; hoặc đơn giản: ở cuối `process_next_job`, nếu
`get_by_id` trả None → cleanup vector vừa ghi. Dài hạn: tombstone document_id để worker
bỏ qua khi phát hiện đã xóa.

## G7-16 — Job FAILED qua reaper/max-attempts KHÔNG publish `doc.status` → client kẹt (P1)

**Vấn đề:** `doc.status` chỉ được publish qua `on_job_finished` trong `run_ingest_worker`
(`runtime.py:369-370`) — tức chỉ khi worker tự hoàn tất job và trả về. Nhưng job vượt
`INGEST_MAX_ATTEMPTS` bị set FAILED bởi `_fail_jobs_exceeding_max_attempts`
(`postgres_document_repository.py:471-509`) — chạy trong claim poll / stale reaper, **không
đi qua worker return path** → `DocStatusPublisher.publish_for_job` không bao giờ được gọi cho
job đó. Document → FAILED trong DB nhưng document-service không nhận `doc.status:failed` →
client treo "processing" cho đến timeout/poll thủ công.

**Fix:** dùng cùng cơ chế `status_published_at` + background sweep như G7-8. Reaper chỉ cần
set job `FAILED` và để `status_published_at = NULL`; sweep sẽ nhặt lại rồi publish `doc.status:failed`.

## G7-17 — Re-ingest ra rỗng KHÔNG prune vector cũ → orphan (P2)

**Vấn đề:** `engine.py:108-117` — khi `chunk_ids` rỗng, hàm `return 0` **trước** bước prune
(`:129-131`). Nếu re-ingest một document mà markdown mới rỗng (parse fail im lặng, OCR ra
trống), vector của lần ingest trước **không bị xóa** → orphan. (Use case sẽ raise
`EmptyIngestResultError` → job FAILED, nhưng vector cũ vẫn nằm lại, query trả nội dung cũ
cho document đã "fail".)

**Fix:** prune `existing_chunk_ids` trước khi return ở nhánh rỗng:

```python
if not chunk_ids:
    existing = await self.vectors.list_chunk_ids_by_document(doc.document_id)
    if existing:
        await self.vectors.delete_many(sorted(existing))
    return 0
```

## G7-18 — `_windows` cũng sinh cửa sổ cuối cụt (đồng hành G7-10) (P2)

**Vấn đề:** G7-10 mới chỉ vá `_cap_words`. `_windows` (`sections.py:79-84`) cũng cắt thuần
theo word + step → cửa sổ cuối có thể chỉ vài từ (vd `len=95, size=90, overlap=15` → window 2
chỉ 20 từ). Đây mới là đơn vị **thực sự được embed** (children), nên ảnh hưởng recall trực
tiếp hơn `_cap_words`.

**Fix:** bỏ window đuôi quá ngắn (vd `< overlap` hoặc `< size*0.3`) bằng cách merge vào
window trước, hoặc dừng khi phần còn lại đã nằm trọn trong window trước.

---

## Bảng tổng hợp bổ sung

| ID | Mức | Vấn đề | File / dòng |
|----|-----|---------|-------------|
| G7-13 | **P0** | Redeliver sau COMPLETED vẫn re-ingest (G7-3 fix chưa đủ) | `ingest_document_use_case.py:59-96` |
| G7-14 | **P1** | `embed_batch` không chia batch → doc lớn fail | `engine.py:121` + `embedding/service.py:27` |
| G7-15 | **P1** | `doc.access delete` đua ingest → vector sống lại | `ingest_consumer.py:150` + `engine.py:128` |
| G7-16 | **P1** | Job FAILED qua reaper không publish doc.status | `postgres_document_repository.py:471` + `runtime.py:369` | CLOSED via doc.status outbox sweep |
| G7-17 | **P2** | Re-ingest rỗng không prune vector cũ | `engine.py:108-117` |
| G7-18 | **P2** | `_windows` sinh cửa sổ cuối cụt | `sections.py:79-84` |

## Tests bổ sung đề xuất

| Test | Covers |
|------|--------|
| Redeliver `doc.ingest` sau COMPLETED → không tạo job mới, không re-embed | G7-13 |
| `embed_batch` với N > batch_size → nhiều request, không vượt giới hạn | G7-14 |
| `delete()` sau khi worker upsert → không còn vector mồ côi | G7-15 |
| Job vượt max_attempts → có publish doc.status:failed | G7-16 |
| Re-ingest markdown rỗng → vector cũ bị prune | G7-17 |

---

# Trước khi fix: dev BẮT BUỘC đọc gì (tránh làm vỡ codebase)

> Codebase này có **constraint cứng** (vi phạm = bug production, không phải style).
> Đọc nền trước, rồi map vào gap mình định fix. Pattern giống G6.

## Đọc nền (mọi gap đều cần)

1. **[handoff/CONSTRAINTS.md](../handoff/CONSTRAINTS.md)** — ràng buộc cứng. Đặc biệt:
   - *§1 Dependency Direction*: use-case layer KHÔNG import SDK; model core KHÔNG dính
     framework/ORM. Mọi I/O qua capability contract. (G7-2/G7-4/G7-13/G7-15 đụng use-case layer
     — `ingest_document_use_case.py` chỉ được gọi qua contract `DocumentRepository`/
     `IngestJobRepository`/`VectorRepository`, KHÔNG chạm SQLAlchemy/boto3/Qdrant SDK.)
   - *§2 Thứ tự ghi để giữ consistency*: đánh dấu *processing* → ghi-đè data chính (id
     deterministic) → *prune phần thừa* → đánh dấu *hoàn tất* → metadata → job log. **Không
     delete-rồi-recreate; không đánh dấu hoàn tất trước khi bước cuối thành công.** (G7-1/G7-14/
     G7-17 đụng đúng bước ghi-đè + prune này.)
   - *§4 Pre-Commit Checklist* (17 câu): tự trả lời TRƯỚC khi commit; "no" nào → không merge.
2. **[handoff/MINDSET.md](../handoff/MINDSET.md)** — vocabulary trung tính (vai trò layer) để
   đọc CONSTRAINTS hiểu đang nói lớp nào.
3. **[decide/NEW_REPO_DECISIONS.md](../decide/NEW_REPO_DECISIONS.md)** + **[handoff/NEW_REPO_DECISIONS.md](../handoff/NEW_REPO_DECISIONS.md)**
   — nếu fix đụng quyết định Day-0 (retry policy, batch size, schema, dimension binding) phải
   cập nhật trước khi merge (checklist #14).
4. **[handoff/DAY0_CHECKLIST.md](../handoff/DAY0_CHECKLIST.md)** + **[handoff/LESSONS.md](../handoff/LESSONS.md)**
   — lỗi đã vấp + lý do quyết định, tránh lặp.

## Map tài liệu ↔ từng gap

| Gap | PHẢI đọc thêm | Constraint dễ vi phạm khi fix |
|---|---|---|
| **G7-1** captioner chunk | [search-split-vectorstore-contract.md](../search-split-vectorstore-contract.md); CONSTRAINTS §2 *Pipeline quality gate*; checklist **#13** | Đổi số chunk/cách embed = đổi retrieval semantics → **BẮT BUỘC chạy eval gate** (golden queries + expected source lineage), không merge bằng "trông đúng". Giữ payload `child_text`/`bm25_text`/`parent_text` đúng vai trò. |
| **G7-2** atomic enqueue | CONSTRAINTS §2 *Document id generation* (idempotent reprocess), *Thứ tự ghi*; checklist #6,#7,#8 | Cleanup Document khi enqueue fail KHÔNG được để orphan/đổi id sang ngẫu nhiên; fix dài hạn (1 transaction) phải ở **adapter layer** (repo), use-case chỉ gọi contract — không nhét SQLAlchemy vào use case. |
| **G7-3 / G7-13** idempotent redeliver | CONSTRAINTS §2 *Document id generation*, *Thứ tự ghi*; checklist **#8** (reprocess idempotent), #10 (test race/idempotency) | Re-ingest cùng `document_id` phải idempotent. G7-13: thêm check COMPLETED ở use-case nhưng đọc status qua contract `get_by_id`, KHÔNG query DB trực tiếp. Giữ parity với `inmemory_document_repository.py` (test 2 backend). |
| **G7-4** ingest timeout | CONSTRAINTS §2 *Runtime config compatibility*; checklist **#7** (timeout/cancel không leak slot), #16 | `asyncio.wait_for` phải giải phóng heartbeat task + claim slot ở `finally` (đã có) — đừng để future treo. Thêm `INGEST_JOB_TIMEOUT_SECONDS` vào `validate_runtime_settings()` (`runtime.py:119`) + test config sai. Lưu ý timeout phải **> stale_timeout** hay không: xem tương tác reaper. |
| **G7-5** caption parallel | CONSTRAINTS §2 *Pipeline quality gate* + checklist **#17** (bước tốn chi phí AI phải có trần) | `asyncio.gather` không giới hạn = bùng request OpenAI → cần semaphore (trần chi phí). Không đổi thứ tự caption↔section (payload phải khớp section). |
| **G7-6** S3 client thread-safe | [ops/s3-client-botocore.md](../ops/s3-client-botocore.md); CONSTRAINTS §2 *Security/resource guards*; checklist #6,#11 | Sửa init phải giữ nguyên 5 lớp guard (HEAD size, stream-to-disk, byte counter, semaphore, finally cleanup). Eager init trong `__init__` không được phá fail-closed startup. |
| **G7-7** fail_exceeding tách | CONSTRAINTS §3 *Schema/adapter*; checklist #10 | Logic ở **adapter layer** (repo) — giữ parity inmemory. Chuyển sang reaper không được làm job vượt max_attempts ngừng được set FAILED (đừng tạo lỗ G6-1 trở lại). |
| **G7-8 / G7-16** doc.status không tới | CONSTRAINTS §2 *Search response schema*/*Fallback behavior*; [ops/ingest-transport.md](../ops/ingest-transport.md); checklist **#4** (đổi contract → thông báo consumer), #12 | doc.status là **contract với document-service** — outbox/retry không được đổi schema payload (`build_doc_status`). G7-16: path reaper-FAILED phải emit status; thêm luồng publish mới = cập nhật doc kiến trúc (checklist #12). |
| **G7-9** SKIP LOCKED | [ops/metadata-db-deploy.md](../ops/metadata-db-deploy.md); CONSTRAINTS §3 *Schema + migration*; checklist #10,#15 | `with_for_update(skip_locked=True)` chỉ chạy trên Postgres — **inmemory + SQLite test fixture không hỗ trợ**; phải giữ optimistic-lock fallback cho 2 backend, không vỡ CI (CI không có Postgres service — xem gap6 §CI). |
| **G7-10 / G7-18** chunk cắt cụt | [search-split-vectorstore-contract.md](../search-split-vectorstore-contract.md); CONSTRAINTS §2 *Pipeline quality gate*; checklist **#13** | Đổi splitter = retrieval semantics → **eval gate bắt buộc**. `_windows` mới phải giữ overlap invariant + thứ tự children. |
| **G7-11** page_number | CONSTRAINTS §2 *Search response schema* (field lineage ổn định) + checklist #4 | `page_number` nằm trong vector payload → là field consumer (query-service) đọc. Đổi tên/đổi nghĩa = breaking contract → version + thông báo. Trước mắt chỉ rename nội bộ `Section`, KHÔNG đổi key payload mà chưa báo. |
| **G7-12** RAM streaming OCR | [ops/native-deps.md](../ops/native-deps.md); CONSTRAINTS §2 *Security/resource guards* (size-before-read); checklist #11 | `images.clear()` không được phá guard size; OCR vẫn đi qua AI gateway (extractor wired ở composition root — `runtime.py:383`), parser KHÔNG tự ôm engine OCR. |
| **G7-14** embed batch | CONSTRAINTS §2 *Embedding dimension↔index binding* + *Runtime config compatibility*; checklist **#13,#17** | Chia batch ở **adapter** (`embedding/service.py`), không ở use-case. Giữ dimension nhất quán ingest↔search (search.md §2). `EMBED_BATCH_SIZE` là param config → validate startup + ghi NEW_REPO_DECISIONS. Đổi embedding path → eval gate. |
| **G7-15** delete đua ingest | CONSTRAINTS §2 *Document id generation* (idempotent, không orphan) + *Thứ tự ghi*; checklist #8,#10 (race) | Fix race phải qua contract (kiểm `get_by_id` None → cleanup vector), KHÔNG để use-case biết SQL. Thêm test race delete↔ingest 2 backend. Giữ idempotent: xóa lại = no-op. |
| **G7-17** empty re-ingest prune | CONSTRAINTS §2 *Thứ tự ghi* ("đơn vị dư bị prune khi bản mới ngắn hơn", kể cả =0); checklist #8,#13 | Prune nhánh rỗng vẫn phải đi qua contract `vectors.delete_many`; đụng pipeline → cân nhắc eval gate (no-answer behavior). |

## Pipeline eval gate — gap nào BẮT BUỘC chạy (checklist #13)

> Nguồn: [search-split-vectorstore-contract.md](../search-split-vectorstore-contract.md) + CONSTRAINTS §2.

**G7-1, G7-5, G7-10, G7-14, G7-17, G7-18** đụng parser/splitter/caption/embedding → **không
merge bằng kiểm thử thủ công**; phải đo lại golden queries + expected source lineage +
no-answer behavior. G7-2/G7-3/G7-4/G7-6/G7-7/G7-8/G7-9/G7-11/G7-12/G7-13/G7-15/G7-16 là
job-lifecycle/transport/infra — **không** đụng retrieval semantics, eval gate không bắt buộc
(trừ khi fix lan sang vector write).

## Parity & CI (đọc trước khi sửa repo layer)

- **Parity 2 backend**: mọi thay đổi `postgres_document_repository.py` phải mirror sang
  `inmemory_document_repository.py` (G6 đã thiết lập); test chạy cả 2. G7-7/G7-9/G7-13/G7-15
  đụng repo → bắt buộc.
- **CI không có Postgres service** (gap6 §"Luồng CI"): suite chính chạy `AI_PROVIDER=offline`,
  job-repo test dùng SQLite/in-memory. G7-9 (`SKIP LOCKED`) chỉ Postgres → test phải skip
  gracefully trên SQLite, không fail CI.
- **Migration có version** (checklist #15): G7 hiện **không gap nào cần schema mới**; nếu fix
  dài hạn G7-2 (transaction) hay G7-8 (bảng outbox) cần bảng/index → viết alembic migration
  idempotent + rollback note, KHÔNG `CREATE` ad-hoc trong code.

---

# Tổng kết triển khai (CLOSED — 2026-06-07)

> Toàn bộ G7-1..G7-18 đã fix qua 7 commit trên `nguyendev`
> (`f94893f` → `1b5e761`). CI xanh (Lint+Test + e2e-cloud). PR #35 → `develop`.
> G7-8 + G7-16 đóng **đúng cơ chế** bằng doc.status outbox sweep (không phải chỉ reconciler).

## Bảng gap → fix → commit

| ID | Mức | Cách fix | Commit | Trạng thái |
|----|-----|----------|--------|-----------|
| G7-1 | P0 | Map đủ children: `to_embed=caption`, `bm25_text=child` | f94893f | ✅ CLOSED |
| G7-2 | P0 | Cleanup khi enqueue fail (sau đổi sang `purge()` hard-delete) | f94893f / 716938b | ✅ CLOSED |
| G7-3 | P0 | `add`+`flush`+bắt `IntegrityError` → trả existing, không overwrite | f94893f | ✅ CLOSED |
| G7-4 | P1 | `asyncio.wait_for` + `INGEST_JOB_TIMEOUT_SECONDS` + validate | f94893f / b8a5eec | ✅ CLOSED |
| G7-5 | P1 | `asyncio.gather` + semaphore `CAPTION_MAX_CONCURRENCY` | f94893f | ✅ CLOSED |
| G7-6 | P1 | Double-checked locking `threading.Lock` | f94893f | ✅ CLOSED |
| G7-7 | P1 | Tách `_fail_jobs_exceeding_max_attempts` khỏi claim → dồn vào reaper (+STALE) | f94893f | ✅ CLOSED |
| G7-8 | P1 | Retry 3 lần **+ doc.status outbox sweep** (at-least-once) | f94893f / 5756c00 | ✅ CLOSED |
| G7-9 | P2 | `with_for_update(skip_locked=True)` (guard chỉ Postgres) | f94893f | ✅ CLOSED |
| G7-10 | P2 | Split sentence-aware, gom câu tới gần max | f94893f | ✅ CLOSED |
| G7-11 | P2 | Rename field `section_index`, giữ nguyên key payload `page_number` | f94893f | ✅ CLOSED |
| G7-12 | P2 | `page.images.clear()` sau OCR mỗi trang (+ fix test snapshot) | f94893f / 1b5e761 | ✅ CLOSED |
| G7-13 | P0 | `enqueue` skip nếu doc đã COMPLETED | f94893f | ✅ CLOSED |
| G7-14 | P1 | Chia batch `EMBED_BATCH_SIZE` trong `embed_batch` | f94893f | ✅ CLOSED |
| G7-15 | P1 | Đảo thứ tự delete + post-check `None or DELETED` + cleanup vector + `fail_job` | f94893f / b8a5eec / 716938b | ✅ CLOSED |
| G7-16 | P1 | doc.status outbox sweep (`status_published_at` + task nền) | 5756c00 / a9d8ba9 | ✅ CLOSED |
| G7-17 | P2 | Prune `existing_chunk_ids` ở nhánh rỗng trước `return 0` | f94893f | ✅ CLOSED |
| G7-18 | P2 | Bỏ window đuôi cụt (`< size*0.3 + overlap`) | f94893f | ✅ CLOSED |

## Hai cơ chế độ bền phát sinh (thiết kế riêng)

| Cơ chế | Đóng lỗ | Cốt lõi | Doc | Commit |
|--------|---------|---------|-----|--------|
| **Store reconciler** | "no-row" (doc.ingest rớt, job chưa từng tạo) | Quét store định kỳ độc lập NATS, enqueue file sót; soft-delete tombstone (`DocumentStatus.DELETED`) chống hồi sinh | [decide/store-reconciler.md](../decide/store-reconciler.md) | 716938b, c4e5219 |
| **doc.status outbox sweep** | "có-row terminal, tín hiệu mất" (G7-8 + G7-16) | `status_published_at` bền trên `ingest_jobs` (migration 0003) + sweep nền phát lại at-least-once; skip doc đã xóa | [decide/doc-status-outbox.md](../decide/doc-status-outbox.md) | 5756c00, a9d8ba9 |

> **Phân biệt 2 lỗ durability:** reconciler đóng lỗ *"doc không có row"*; outbox sweep đóng lỗ
> *"doc có row terminal nhưng tín hiệu doc.status không tới"*. Reconciler **không** thay được
> outbox vì nó skip mọi row đã tồn tại (kể cả FAILED/COMPLETED).

## Phát hiện ngoài lề trong review (đã fix kèm)

- **Validate env bỏ qua trên đường config.yaml** (production): gom env mới + reconciler/sweep
  vào `validate_ingest_runtime_limits()` gọi ở **cả 2 đường** → fail-closed startup. (b8a5eec / 716938b / 5756c00)
- **Soft-delete làm vỡ G7-15 race guard + lộ DELETED**: sửa guard `None or DELETED`, lọc
  DELETED khỏi `list_all`, edge 404, chặn rời DELETED trong `update_status`, parity in-memory. (716938b)
- **Reconciler misconfig im lặng** (bật nhưng parser không S3): thêm log WARNING chẩn đoán. (c4e5219)
- **CI Lint+Test failed**: test G7-12 giữ reference sống tới list bị `clear()` → snapshot
  `list(images)` tại call-time, giữ nguyên tối ưu RAM. (1b5e761)

## Nguyên tắc giữ vững khi fix

- Parity Postgres ↔ in-memory (test cả 2 backend).
- Không phá §1 dependency direction: sweep/reconciler ở **runtime layer**, repository/reaper
  không biết NATS.
- Không đổi schema payload `doc.status` (§2 contract với document-service).
- Migration `0003` có version + rollback; chạy được cả SQLite (CI) lẫn Postgres.
