# doc.status outbox-lite — đảm bảo phát trạng thái terminal (đóng G7-16 + G7-8)

> **Loại tài liệu:** Implementation guide cho team dev. Đọc *Bối cảnh* + *Quyết định
> thiết kế* trước khi code. Toàn bộ thay đổi **nằm trong rag-worker** (không đụng
> document-service).
>
> **Trạng thái:** IMPLEMENTED (2026-06-07).
> **Liên quan:** [gap/gap7.md](../gap/gap7.md) G7-16, G7-8. [store-reconciler.md](./store-reconciler.md)
> (đóng lỗ "no-row"; file này đóng lỗ "có-row terminal nhưng tín hiệu mất").
> **Grounding:** code review `nguyendev` HEAD 2026-06-07.

---

## 1. Bối cảnh — vì sao store reconciler CHƯA đủ

### Hai lỗ khác nhau

`doc.status` là tín hiệu duy nhất rag-worker báo kết cục ingest cho document-service.
document-service set DB của nó về `indexed`/`failed` **chỉ khi nhận được tín hiệu này**;
không nhận → kẹt `processing` vĩnh viễn ("client kẹt").

| Lỗ | Mô tả | Có row `documents`? | Ai đóng |
|---|---|---|---|
| **A — no-row** | `doc.ingest` rớt → rag-worker chưa từng biết doc | KHÔNG | **store reconciler** (đã làm) |
| **B — có-row terminal, tín hiệu mất** | rag-worker đã xử lý, có row FAILED/COMPLETED, nhưng `doc.status` không phát được | CÓ | **file này** |

### Vì sao reconciler không chạm lỗ B

[reconcile_store_once](../../app/application/use_cases/ingestion/store_reconciler.py) bỏ qua mọi
object đã có row:

```python
existing = await ingest_use_case.get_document(doc_id)
if existing is not None:        # row bất kỳ status (kể cả FAILED/COMPLETED) -> SKIP
    continue
```

Nên hai kịch bản B vẫn hở:

- **G7-16:** job crash tới `INGEST_MAX_ATTEMPTS` → `_fail_jobs_exceeding_max_attempts`
  ([postgres_document_repository.py](../../app/infrastructure/db/postgres_document_repository.py))
  set row `FAILED` **trong reaper/claim poll — không đi qua chỗ publish `doc.status`** → tín
  hiệu `failed` không bao giờ phát. Reconciler thấy row FAILED → skip → client kẹt.
- **G7-8:** job `COMPLETED`, có gọi publish nhưng NATS chết đúng lúc (kể cả sau 3 lần retry)
  → tín hiệu `indexed` mất. Reconciler thấy row COMPLETED → skip → client kẹt.

> Reconciler **cố tình** skip FAILED (nếu enqueue lại file hỏng vĩnh viễn → poison loop vô
> tận). Skip là đúng — nhưng đã skip thì **phải có đường khác phát tín hiệu** cho hai lỗ này.

### Vì sao chỉ cần sửa rag-worker là đủ

Bản chất G7-16/G7-8 = *"rag-worker không gửi được tín hiệu"*, mà việc gửi nằm hoàn toàn trong
rag-worker. document-service vốn tiêu thụ `doc.status` đúng. Nên chỉ cần đảm bảo rag-worker
**chắc chắn gửi, sớm muộn cũng gửi** là đóng được — không cần đụng document-service.

---

## 2. Quyết định thiết kế: "đã phát chưa" là một BIT BỀN + sweep thử lại

Hiện `doc.status` phát **đúng một lần, ngay lúc worker xong job**
([runtime.py](../../app/interfaces/api/runtime.py) `run_ingest_worker` → `on_job_finished`).
Trượt một lần là mất.

Sửa thành **at-least-once**:

1. Mỗi job terminal mang một cờ bền **"đã phát doc.status chưa"** (`status_published_at`).
2. Một **sweep nền** quét job *terminal nhưng chưa phát* → phát → đánh dấu đã phát.
3. Cờ nằm trong DB → sống qua restart; sweep chạy lại → cuối cùng mọi job terminal đều được phát.

### Vì sao đóng được cả hai

- G7-16: row FAILED do reaper có cờ "chưa phát" → sweep nhặt → phát `failed`.
- G7-8: row COMPLETED publish trượt có cờ "chưa phát" → sweep nhặt → phát lại.
- Restart: cờ bền → không mất.

### Vì sao at-least-once là đủ (không cần exactly-once)

`doc.status` **idempotent** phía document-service (set về `indexed`/`failed`; gửi 2 lần = vô
hại). Nên phát trùng không sai → ta chỉ cần đảm bảo "phát ít nhất một lần", không cần khoá
phức tạp.

### Bắt buộc có migration

"Đã phát chưa" là một bit MỚI, **không suy ra được** từ trạng thái sẵn có (`documents.status`
chỉ nói doc xong/lỗi, không nói document-service đã nhận tín hiệu chưa), và **phải sống qua
restart** (restart chính là lúc cần độ bền nhất). Không né được persistence → thêm 1 cột.
Repo đã có alembic (0001/0002); thêm cột nullable = rủi ro thấp, idempotent.

---

## 3. Lựa chọn: giữ phát inline hay chỉ sweep

| Phương án | Cách chạy | Ưu | Nhược |
|---|---|---|---|
| **A. Giữ inline + đánh dấu** *(khuyến nghị)* | Worker vẫn phát ngay sau job; phát OK thì `mark_status_published`. Sweep chỉ nhặt phần sót (reaper-FAILED, inline trượt). | Độ trễ ~tức thì cho case thường; sweep là lưới an toàn. | 2 đường phát (đều idempotent nên ok). |
| **B. Bỏ inline, chỉ sweep** | Worker không phát; sweep là đường phát duy nhất, interval ngắn (vd 10–15s). | Một đường duy nhất, code gọn nhất, không lo phát trùng. | doc.status trễ tối đa một interval. |

**Khuyến nghị: phương án A** — giữ độ trễ thấp hiện có, thêm sweep làm lưới bền. File này mô tả
theo A; muốn B thì bỏ bước inline-mark (4c) và để sweep interval ngắn.

---

## 4. Cần thực hiện gì

### 4a. Schema — migration `0003`

File mới `migrations/versions/0003_doc_status_outbox.py` (theo pattern
[0002](../../migrations/versions/0002_ingest_job_guardrails.py)):

```python
revision = "0003_doc_status_outbox"
down_revision = "0002_ingest_job_guardrails"

def upgrade() -> None:
    op.add_column(
        "ingest_jobs",
        sa.Column("status_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    dialect = op.get_bind().dialect.name
    where = sa.text("status IN ('COMPLETED','FAILED') AND status_published_at IS NULL")
    kwargs = {}
    if dialect == "postgresql":
        kwargs["postgresql_where"] = where
    elif dialect == "sqlite":
        kwargs["sqlite_where"] = where
    op.create_index(
        "ix_ingest_jobs_unpublished_terminal",
        "ingest_jobs",
        ["updated_at"],
        **kwargs,
    )

def downgrade() -> None:
    op.drop_index("ix_ingest_jobs_unpublished_terminal", table_name="ingest_jobs")
    op.drop_column("ingest_jobs", "status_published_at")
```

> Cột nullable mặc định NULL → mọi job terminal hiện hữu được coi là "chưa phát" → sweep sẽ
> phát một lần cho lịch sử gần (xem giới hạn lookback ở 4d). Idempotent nên không sao.

### 4b. Model + entity

- [models.py](../../app/infrastructure/db/models.py) `IngestJobRecord`: thêm
  `status_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)`.
- [domain/entities/ingest_job.py](../../app/domain/entities/ingest_job.py) `IngestJob`: thêm
  field `status_published_at: datetime | None = None`. Cập nhật `_to_job` (postgres) + chỗ dựng
  IngestJob (in-memory) để map cột mới.

### 4c. Repository contract + 2 backend (parity)

Thêm vào [ingest_job_repository.py](../../app/domain/repositories/ingest_job_repository.py):

```python
@abstractmethod
async def list_pending_status_publications(self, limit: int, *, older_than: datetime | None = None) -> list[IngestJob]:
    """Terminal jobs (COMPLETED/FAILED) chưa phát doc.status (status_published_at IS NULL)."""

@abstractmethod
async def mark_status_published(self, job_id: str) -> None:
    """Đánh dấu job đã phát doc.status thành công."""
```

**Postgres** ([postgres_document_repository.py](../../app/infrastructure/db/postgres_document_repository.py)):

```python
def _list_pending_status_publications_sync(self, limit, older_than):
    with self._session() as session:
        stmt = (select(IngestJobRecord)
                .where(IngestJobRecord.status.in_([IngestJobStatus.COMPLETED.value,
                                                   IngestJobStatus.FAILED.value]),
                       IngestJobRecord.status_published_at.is_(None))
                .order_by(IngestJobRecord.updated_at.asc())
                .limit(limit))
        if older_than is not None:   # lookback: bỏ qua lịch sử quá cũ khi mới bật
            stmt = stmt.where(IngestJobRecord.updated_at >= older_than)
        return [self._to_job(r) for r in session.execute(stmt).scalars().all()]

def _mark_status_published_sync(self, job_id):
    with self._session() as session:
        record = session.get(IngestJobRecord, job_id)
        if record is not None:
            record.status_published_at = datetime.now(UTC)
```

**In-memory** ([inmemory_document_repository.py](../../app/infrastructure/db/inmemory_document_repository.py)):
mirror y hệt — lọc `status in {COMPLETED,FAILED}` và `status_published_at is None`, sort theo
`updated_at`, `mark` = `replace(job, status_published_at=now)`.

> **Inline-mark (phương án A):** ở [runtime.py](../../app/interfaces/api/runtime.py)
> `run_ingest_worker`, sau khi `on_job_finished(job)` phát thành công → gọi
> `mark_status_published(job.id)`. Cần `on_job_finished` trả bool (xem 4e). Nếu chọn phương án
> B thì bỏ bước này.

### 4d. Sweep task (runtime)

Trong [runtime.py](../../app/interfaces/api/runtime.py), cạnh `run_stale_job_reaper`:

```python
@dataclass(frozen=True)
class DocStatusSweepSettings:
    interval_seconds: float = 30.0
    batch: int = 100
    lookback_seconds: int = 86_400   # chỉ phát lại lịch sử trong 24h khi mới bật

async def run_doc_status_publisher_sweep(job_repository, publisher, settings, logger):
    while True:
        try:
            cutoff = datetime.now(UTC) - timedelta(seconds=settings.lookback_seconds)
            jobs = await job_repository.list_pending_status_publications(settings.batch, older_than=cutoff)
            for job in jobs:
                if await publisher.publish_for_job(job):       # trả bool (4e)
                    await job_repository.mark_status_published(job.id)
        except Exception as exc:  # noqa: BLE001 - maintenance task phải sống tiếp
            log_event(logger, logging.WARNING, "doc_status_sweep_failed", stage="status", error=str(exc))
        await asyncio.sleep(settings.interval_seconds)
```

> `older_than` (lookback) tránh việc lần đầu bật quét cả lịch sử cũ vô tận. Mốc phải đủ rộng
> (mặc định 24h). Nếu một job terminal cũ hơn lookback chưa phát → bỏ (chấp nhận: cực hiếm,
> chỉ xảy ra nếu NATS chết liên tục > lookback).

### 4e. `publish_for_job` trả bool

[ingest_consumer.py](../../app/interfaces/nats/ingest_consumer.py) `DocStatusPublisher.publish_for_job`:
hiện trả `None`. Đổi: trả `True` khi publish OK, `False` khi hết retry vẫn lỗi (hoặc `True`
khi message is None — không có gì để phát coi như xong, không cần đánh dấu lại). Caller inline
cũ (`on_job_finished`) có thể bỏ qua giá trị; sweep dùng nó để quyết định `mark`.

```python
async def publish_for_job(self, job) -> bool:
    message = build_doc_status(job)
    if message is None:
        return True          # non-terminal: coi như không cần phát
    for attempt in range(3):
        try:
            await self._broker.publish_json(self._subject, message)
            return True
        except Exception as exc:  # noqa: BLE001
            if attempt == 2:
                self._logger.error("doc_status_publish_failed_terminal doc_id=%s error=%s", job.document_id, exc)
                return False
            await asyncio.sleep(0.5 * (2 ** attempt))
    return False
```

### 4f. Config + validate

| Env | Mặc định | Ý nghĩa |
|---|---|---|
| `DOC_STATUS_SWEEP_INTERVAL_SECONDS` | `30` | Chu kỳ sweep |
| `DOC_STATUS_SWEEP_BATCH` | `100` | Số job mỗi sweep |
| `DOC_STATUS_SWEEP_LOOKBACK_SECONDS` | `86400` | Chỉ phát lại lịch sử trong cửa sổ này |

Thêm vào `validate_ingest_runtime_limits()`
([runtime.py](../../app/interfaces/api/runtime.py)): các giá trị > 0 (lookback >= 0). Sweep
chỉ liên quan khi NATS bật — validate vô điều kiện vẫn ok (giá trị mặc định hợp lệ).

### 4g. Wiring trong `lifespan`

Chỉ tạo sweep task khi **`status_publisher is not None`** (NATS bật) — không có publisher thì
phát đi đâu. Cancel/await khi shutdown như các task khác.

```python
status_sweep_task = None
if status_publisher is not None and runtime.job_repository is not None:
    status_sweep_task = asyncio.create_task(
        run_doc_status_publisher_sweep(runtime.job_repository, status_publisher, sweep_settings, logger)
    )
# ... app.state.doc_status_sweep_task = status_sweep_task
# ... finally: cancel + await
```

---

## 5. Test

| Test | Covers |
|------|--------|
| reaper set job FAILED → `status_published_at` NULL → sweep phát `failed` → đánh dấu | G7-16 |
| job COMPLETED, inline publish trượt → sweep phát `indexed` → đánh dấu | G7-8 |
| inline publish OK → đánh dấu ngay → sweep KHÔNG phát lại (phương án A) | 4c/4e |
| `list_pending_status_publications` chỉ trả COMPLETED/FAILED chưa phát, sort `updated_at`, tôn trọng `older_than` | 4c |
| `mark_status_published` set timestamp; phát 2 lần (idempotent) không vỡ | §2 |
| restart sim: job terminal + chưa phát còn trong DB → sweep phát | §2 |
| sweep KHÔNG chạy khi NATS tắt (`status_publisher is None`) | 4g |
| parity in-memory ≡ postgres | A/B |
| migration 0003 upgrade/downgrade idempotent (sqlite + postgres) | 4a |

Suite chính chạy `AI_PROVIDER=offline`, không cần NATS thật (publisher giả như test hiện có
trong [test_ingest_consumer.py](../../tests/interfaces/nats/test_ingest_consumer.py)).

---

## 6. Ràng buộc & doc bắt buộc (CONSTRAINTS)

> [handoff/CONSTRAINTS.md](../handoff/CONSTRAINTS.md) §4 checklist.

- **#1 dependency direction:** sweep ở **tầng runtime** (như `run_ingest_worker`), đọc repo qua
  contract + gọi publisher đã wire. Reaper/repository **không** import NATS. Không vi phạm.
- **#4 contract với consumer:** KHÔNG đổi schema payload `doc.status` (`build_doc_status` giữ
  nguyên `{doc_id, status, chunk_count|error}`) — chỉ đổi *thời điểm/độ tin cậy* phát, không
  đổi nội dung. Không cần thông báo document-service.
- **#7 failure path:** sweep phải sống tiếp khi 1 job lỗi (except + log, không chết task).
- **#10 test race/idempotency:** test phát trùng + restart bắt buộc.
- **#15 migration:** 0003 có version + rollback note; chạy được cả sqlite (test/CI) lẫn postgres.
- Cập nhật [gap/gap7.md](../gap/gap7.md): G7-16 + G7-8 → **CLOSED via doc.status outbox sweep**
  (lần này đúng cơ chế). Đồng bộ phần thân G7-16 (đang mô tả outbox) với bảng trạng thái.
- Cập nhật [decide/NEW_REPO_DECISIONS.md](./NEW_REPO_DECISIONS.md): quyết định
  "doc.status at-least-once qua outbox sweep trong rag-worker".
- Cập nhật [ops/ingest-transport.md](../ops/ingest-transport.md): mô tả đảm bảo at-least-once
  + cờ `status_published_at` + sweep.

---

## 7. Thứ tự thực hiện (checklist)

```
 [x] 4a  migration 0003: cột status_published_at + partial index
 [x] 4b  model IngestJobRecord + entity IngestJob + mapping (_to_job, in-memory)
 [x] 4c  contract + postgres + in-memory: list_pending_status_publications, mark_status_published
 [x] 4e  publish_for_job -> bool (giữ retry hiện có)
 [x] 4d  run_doc_status_publisher_sweep + DocStatusSweepSettings
 [x] 4f  config + validate (interval/batch/lookback)
 [x] 4g  wiring lifespan (chỉ khi status_publisher != None) + inline-mark (phương án A)
 [x] 5   test (G7-16, G7-8, idempotent, restart, parity, migration)
 [x] 6   cập nhật gap7.md + NEW_REPO_DECISIONS.md + ingest-transport.md
 [x] ── pytest tests -q --ignore=tests/e2e  (AI_PROVIDER=offline) ──
```

**Điểm dễ sai:**
- Quên đánh dấu inline (4c/4g phương án A) → sweep phát trùng mọi job (vẫn đúng nhờ idempotent
  nhưng tốn NATS traffic). Không phải bug, nhưng nên có.
- `publish_for_job` trả `True` cho message None — nếu trả False sẽ kẹt sweep lặp vô ích trên job
  non-terminal (thực ra sweep chỉ query terminal nên ít xảy ra, vẫn nên đúng).
- Lookback quá ngắn → job terminal cũ chưa phát bị bỏ. Để mặc định rộng (24h).

---

## 8. Quyết định còn mở

1. **Phương án A (giữ inline) vs B (sweep-only)** — mặc định A. Chốt trước khi code 4c/4g.
2. **Prune cột cũ:** không cần — `status_published_at` chỉ là timestamp trên row đã có; row
   ingest_jobs vốn được dọn khi `delete()`/purge. Không thêm gánh nặng retention.
3. **Lookback mặc định 24h** — nới nếu môi trường có thể mất NATS lâu hơn.
```
