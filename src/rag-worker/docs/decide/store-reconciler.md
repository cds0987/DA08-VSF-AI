# Store Reconciler — quét store định kỳ bắt file sót (đóng G7-16 / G7-8)

> **Loại tài liệu:** Implementation guide cho team dev. Đọc hết phần *Bối cảnh* +
> *Quyết định thiết kế* trước khi code. Phần *Thực hiện* chia 2 mảng A/B theo đúng
> thứ tự phụ thuộc — làm A xong, xanh test, rồi mới sang B.
>
> **Trạng thái:** PLANNED — chưa code.
> **Liên quan:** [gap/gap7.md](../gap/gap7.md) G7-16 (job FAILED qua reaper không
> publish doc.status), G7-8 (publish best-effort). [ops/ingest-transport.md](../ops/ingest-transport.md).
> **Grounding:** code review `nguyendev` HEAD 2026-06-07.

---

## 1. Bối cảnh — vì sao cần

### Vấn đề gốc

Trạng thái ingest hiện được báo cho document-service **chỉ qua sự kiện NATS `doc.status`**,
phát từ đúng một chỗ: worker chạy xong job rồi return → `on_job_finished` →
`DocStatusPublisher.publish_for_job` ([runtime.py](../../app/interfaces/api/runtime.py)
`run_ingest_worker`).

Có **2 lỗ** khiến document-service / người dùng kẹt ở trạng thái "processing":

- **G7-16:** job vượt `INGEST_MAX_ATTEMPTS` bị set FAILED bởi
  `_fail_jobs_exceeding_max_attempts` ([postgres_document_repository.py](../../app/infrastructure/db/postgres_document_repository.py))
  — chạy trong reaper/claim poll, **không đi qua worker return path** → không ai gọi
  publisher → document FAILED trong DB nhưng tín hiệu không bao giờ ra ngoài.
- **G7-8:** `publish_for_job` là best-effort (đã có retry 3 lần nhưng vẫn có thể mất nếu
  NATS chết lâu). `doc.ingest` cũng có thể bị rớt trước khi tạo job.

### Hướng xử lý (đã chốt với team)

Thay vì cố đảm bảo exactly-once qua message (outbox), ta thêm **một reconciler quét store
định kỳ, độc lập NATS và độc lập document-service**: nó tự liệt kê object trong bucket,
tìm file nào rag-worker **chưa từng biết**, rồi enqueue lại qua use-case sẵn có.

Hệ quả: `doc.status` trở thành **best-effort optimization**. G7-16 và G7-8 **tụt từ "bug"
xuống "trễ tối đa một chu kỳ quét"**. Đồng thời reconciler bắt luôn cả message NATS rớt,
worker chết lúc nhận, file upload khi rag-worker down.

### Phạm vi khảo sát document-service (đã làm)

- **Không cần sửa document-service.** Object key có layout cố định
  `raw/{document_id}/{filename}` ([upload_document_use_case.py](../../../document-service/app/application/use_cases/documents/upload_document_use_case.py)),
  nên reconciler suy ra được `doc_id`, `document_name`, `file_type` thuần từ key.
- classification/ACL **không** nằm trong key, nhưng rag-worker vốn không enforce ACL → không sao.
- **Coupling duy nhất:** reconciler phụ thuộc convention `raw/<doc_id>/<file>`. Nếu
  document-service đổi layout → reconciler gãy. Phải pin convention bằng constant + ghi doc.

---

## 2. Quyết định thiết kế cốt lõi: `documents` là SỔ ĐĂNG KÝ

Câu hỏi mấu chốt của reconciler: *"object này đã được xử lý chưa?"* Nguồn sự thật là bảng
`documents` của rag-worker. Một row tồn tại = "rag-worker đã biết về doc này". Trạng thái
row kể câu chuyện:

| Row trong `documents` | Nghĩa | Reconciler |
|---|---|---|
| `completed` | đã index xong | **skip** |
| `failed` | đã thử, bỏ cuộc (poison) | **skip** |
| `queued` / `processing` | đang trong luồng | **skip** |
| `deleted` | đã xử lý rồi bị xóa có chủ đích | **skip** |
| **(không có row)** | thật sự chưa từng biết | **ENQUEUE** |

### Vì sao phải SOFT-DELETE

Hiện `delete()` **xóa hẳn row** → sổ đăng ký "quên" rằng doc từng tồn tại. Khi đó nếu object
còn sót trong bucket (document-service xóa object là best-effort, nuốt lỗi — xem
[delete_document_use_case.py](../../../document-service/app/application/use_cases/documents/delete_document_use_case.py)),
lần quét sau reconciler thấy *"object có, không row"* → **ingest lại doc người dùng đã xóa →
vector sống lại**. Đây là lỗi "hồi sinh".

**Giải pháp:** đổi `delete()` thành **soft-delete** — giữ row, đặt `status=DELETED`, vẫn xóa
vector + ingest_jobs + job_logs. Bia mộ DELETED trong chính bảng `documents` đóng vai trò
tombstone → reconciler skip → không hồi sinh. **Không cần bảng tombstone riêng, không cần
migration** (status là cột `String(32)`, thêm giá trị enum mới).

### Các đánh đổi đã chốt

- **Poison (FAILED):** skip mặc định, không tự retry (file hỏng vĩnh viễn không quét lại vô hạn).
- **Reconciler additive-only:** chỉ THÊM (enqueue file sót), không tự xóa gì. Xóa vẫn đi qua
  `doc.access{deleted:true}`.
- **Opt-in:** mặc định TẮT (tránh chi phí list bucket bất ngờ); deploy bật qua env.
- **Eventual consistency:** chấp nhận trễ tới một chu kỳ quét; đổi lại đơn giản + robust hơn outbox.

---

## 3. PHẦN A — Refactor soft-delete (làm trước, độc lập reconciler)

> Mảng này **tự nó có giá trị** (sửa đúng ngữ nghĩa delete + vá tương tác G7-15) và là tiền
> đề cho reconciler. Hoàn thành + xanh test rồi mới sang Phần B.

### A0. Thêm enum `DELETED`

File [domain/entities/document.py](../../app/domain/entities/document.py):

```python
class DocumentStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"        # ← thêm; tombstone, terminal
```

Không cần migration (cột `documents.status` là `String(32)`).

### A1. Soft-delete ở repository (parity 2 backend)

**Postgres** — `_delete_sync` ([postgres_document_repository.py](../../app/infrastructure/db/postgres_document_repository.py)):
giữ nguyên xóa `job_logs` + `ingest_jobs`, nhưng **thay** `DELETE documents` bằng UPDATE status:

```python
def _delete_sync(self, document_id: str) -> None:
    with self._session() as session:
        session.execute(delete(JobLogRecord).where(JobLogRecord.document_id == document_id))
        session.execute(delete(IngestJobRecord).where(IngestJobRecord.document_id == document_id))
        record = session.get(DocumentRecord, document_id)
        if record is not None:
            record.status = DocumentStatus.DELETED.value
            record.error_message = None
        # KHÔNG xóa row documents — giữ làm tombstone cho reconciler
```

> Lưu ý: vẫn xóa `ingest_jobs` để re-ingest cùng id (nếu có) không vướng active-job index;
> giữ row `documents` DELETED.

**In-memory** — `delete()` ([inmemory_document_repository.py](../../app/infrastructure/db/inmemory_document_repository.py)):

```python
async def delete(self, document_id: str) -> None:
    doc = self._documents.get(document_id)
    if doc is not None:
        self._documents[document_id] = replace(doc, status=DocumentStatus.DELETED, error_message=None)
    self._job_logs = [e for e in self._job_logs if e.document_id != document_id]
    self._jobs = {jid: j for jid, j in self._jobs.items() if j.document_id != document_id}
```

### A2. Chặn rời khỏi DELETED trong `update_status` (cả 2 backend)

DELETED là terminal — không cho job/luồng nào kéo status ngược lại. Sửa `_update_status_sync`
(postgres) và `update_status` (in-memory): nếu row đang `DELETED` thì **bỏ qua** (no-op),
trừ khi status mới cũng là DELETED.

Postgres:
```python
def _update_status_sync(self, document_id, status, error):
    with self._session() as session:
        record = session.get(DocumentRecord, document_id)
        if record is None:
            raise KeyError(f"document not found: {document_id}")
        if record.status == DocumentStatus.DELETED.value and status is not DocumentStatus.DELETED:
            return  # tombstone bất biến
        record.status = status.value
        if error is not None:
            record.error_message = error
        elif status is DocumentStatus.COMPLETED:
            record.error_message = None
```
In-memory mirror y hệt (thêm guard trước `replace`).

> **Vì sao cần:** đầu `process_next_job` gọi `update_status(..., PROCESSING)`
> ([use_case.py](../../app/application/use_cases/ingestion/ingest_document_use_case.py)).
> Nếu doc bị xóa trước khi job được claim, không có guard này nó sẽ kéo DELETED → PROCESSING.

### A3. Sửa G7-15 race guard (điểm dễ vỡ nhất)

Trong `process_next_job` ([use_case.py](../../app/application/use_cases/ingestion/ingest_document_use_case.py))
— đoạn check sau `finally` (thêm ở commit b8a5eec). **Hiện dựa vào `get_by_id is None`**, sẽ
chết im lặng vì soft-delete giữ row:

```python
# TRƯỚC:
if await self._documents.get_by_id(job.document_id) is None:
    ...

# SAU:
doc = await self._documents.get_by_id(job.document_id)
if doc is None or doc.status is DocumentStatus.DELETED:
    await self._engine.vectors.delete_by_document(job.document_id)
    await self._jobs.fail_job(job.id, claim_id, error_message="document deleted during ingest")
    return await self._jobs.get_job(job.id)
```

### A4. Ẩn DELETED khỏi listing, NHƯNG giữ `get_by_id` thấy DELETED

- `_list_all_sync` (postgres) + `list_all` (in-memory): thêm filter
  `status != DELETED`. (Postgres: `.where(DocumentRecord.status != DocumentStatus.DELETED.value)`;
  in-memory: list-comprehension lọc.)
- **`get_by_id` GIỮ NGUYÊN trả cả row DELETED** — reconciler + race guard cần thấy tombstone.
- Tầng edge `get_document` ([routers/ingest.py](../../app/interfaces/api/routers/ingest.py) /
  use-case `get_document`): map `status == DELETED → HTTP 404` để API public không lộ doc đã xóa.

> **Nguyên tắc:** logic "ẩn DELETED" thuộc **edge/listing**, KHÔNG nhét vào `get_by_id` của
> repository — nếu repository tự giấu DELETED thì reconciler mù, hồi sinh trở lại.

### A5. `create()` trên row DELETED — KHÔNG revive (mặc định)

Không đổi code `create()`. Giữ hành vi: gặp row tồn tại (kể cả DELETED) → trả existing, không
tạo job. Lý do an toàn: re-upload luôn sinh `uuid4()` mới → doc_id mới → key mới; reconciler
skip mọi row có sẵn nên không bao giờ chạm đường này. **Ghi rõ giả định** "DELETED là terminal,
re-ingest cùng doc_id không được hỗ trợ" vào docstring `create()` để người sau không bối rối.

### A6. Cập nhật test cũ (sẽ đỏ ngay khi đổi)

3 chỗ assert "row biến mất" phải đổi sang ngữ nghĩa tombstone:

- [test_postgres_document_repository.py](../../tests/infrastructure/db/test_postgres_document_repository.py)
  `~:59-60` và `_delete_cascades_jobs_and_logs ~:143-147`:
  ```python
  await repository.delete("doc-1")
  deleted = await repository.get_by_id("doc-1")
  assert deleted is not None and deleted.status is DocumentStatus.DELETED  # tombstone còn
  assert await repository.get_job("job-1") is None        # jobs đã dọn
  assert await repository.list_job_logs("doc-1") == []    # logs đã dọn
  assert await repository.list_all() == []                # ẩn khỏi listing
  ```
- [test_ingest_document_use_case.py](../../tests/application/ingestion/test_ingest_document_use_case.py)
  `~:240` (`use_case.delete(...)`) + test delete-race của G7-15: mô phỏng "đã xóa" bằng cách
  set `status=DELETED` (qua `delete()`), **không** pop row thủ công. Đảm bảo guard A3 vẫn bắt.

### A7. Test mới cho Phần A

| Test | Covers |
|------|--------|
| `delete()` → row còn, status=DELETED, jobs+logs dọn sạch, không hiện ở `list_all` (2 backend) | A1/A4 |
| `update_status` trên row DELETED → no-op (không kéo về PROCESSING/COMPLETED) | A2 |
| race: doc bị `delete()` trong lúc ingest → sau ingest vector bị dọn + job FAILED | A3 |
| `get_document` (edge) trên doc DELETED → 404; nhưng `get_by_id` (repo) vẫn trả row | A4 |

---

## 4. PHẦN B — Reconciler

### B1. Capability mới: `ObjectStoreLister`

rag-worker chưa có khả năng **list** object (S3SourceParser chỉ `head_object`/`get_object`).
Thêm contract ở [domain/repositories/](../../app/domain/repositories/):

```python
# domain/repositories/object_store_lister.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator

@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    last_modified: datetime

class ObjectStoreLister(ABC):
    @abstractmethod
    def list_objects(self, prefix: str) -> AsyncIterator[StoredObject]:
        """Yield mọi object dưới prefix (đã phân trang). Async iterator."""
```

**Adapter S3** (infrastructure/external/) dùng `list_objects_v2` paginator, **tái dùng boto3
client + credentials của S3SourceParser** (rag-worker đọc bucket qua botocore — xem
[ops/s3-client-botocore.md](../ops/s3-client-botocore.md)). Phân trang bằng
`ContinuationToken`; bọc call blocking trong `asyncio.to_thread`. Tôn trọng allow-list bucket
+ guard như S3SourceParser (CONSTRAINTS §2 Security/resource guards).

> Nếu store là GCS qua S3-interop/R2 thì `list_objects_v2` vẫn chạy qua cùng endpoint boto3
> đang dùng. Không tự thêm SDK GCS native vào runtime path.

### B2. Key parser

```python
# core_engine hoặc app/interfaces — nơi sở hữu convention
RAW_PREFIX = "raw/"   # constant; PIN convention với document-service

def parse_object_key(key: str) -> tuple[str, str, str] | None:
    # raw/<doc_id>/<filename> -> (doc_id, document_name, file_type)
    if not key.startswith(RAW_PREFIX):
        return None
    rest = key[len(RAW_PREFIX):]
    parts = rest.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    doc_id, filename = parts[0], parts[1]
    if "." not in filename:
        return None
    file_type = filename.rsplit(".", 1)[1].lower()
    return doc_id, filename, file_type
```
Loại key sai format / file_type không hỗ trợ (đối chiếu allow-list extension nếu cần).

### B3. Reconciler loop

Đặt trong [runtime.py](../../app/interfaces/api/runtime.py) cạnh `run_stale_job_reaper`
(cùng pattern background task):

```python
async def reconcile_store_once(lister, ingest_use_case, settings, logger) -> int:
    scanned = enqueued = 0
    now = datetime.now(UTC)
    async for obj in lister.list_objects(RAW_PREFIX):
        scanned += 1
        parsed = parse_object_key(obj.key)
        if parsed is None:
            continue
        doc_id, name, file_type = parsed
        # bỏ qua object mới (đua với doc.ingest đang bay)
        if (now - obj.last_modified).total_seconds() < settings.min_age_seconds:
            continue
        existing = await ingest_use_case.get_document(doc_id)
        if existing is not None:
            continue   # có row bất kỳ status (kể cả DELETED) -> skip
        await ingest_use_case.enqueue(
            document_id=doc_id, document_name=name, file_type=file_type,
            markdown=None, source_uri=f"s3://{settings.bucket}/{obj.key}",
            correlation_id=f"reconcile:{doc_id}",
        )
        enqueued += 1
    log_event(logger, logging.INFO, "store_reconcile_completed",
              stage="reconcile", scanned=scanned, enqueued=enqueued)
    return enqueued

async def run_store_reconciler(lister, ingest_use_case, settings, logger):
    while True:
        try:
            await reconcile_store_once(lister, ingest_use_case, settings, logger)
        except Exception as exc:  # noqa: BLE001 - maintenance task phải sống tiếp
            log_event(logger, logging.WARNING, "store_reconcile_failed", stage="reconcile", error=str(exc))
        await asyncio.sleep(settings.interval_seconds)
```

> **Idempotent kép:** dù table-check ở trên có miss, `enqueue` vẫn dedup qua `find_active_job`
> + skip-COMPLETED (G7-13). Table-check chỉ để giảm log spam + tránh tạo job thừa.

### B4. Config + validate

| Env | Mặc định | Ý nghĩa |
|---|---|---|
| `STORE_RECONCILE_ENABLED` | `0` (tắt) | Bật reconciler (opt-in) |
| `STORE_RECONCILE_INTERVAL_SECONDS` | `900` | Chu kỳ quét |
| `STORE_RECONCILE_MIN_AGE_SECONDS` | `600` | Bỏ qua object mới hơn ngưỡng (tránh đua doc.ingest) |
| `S3_SOURCE_BUCKET` / `R2_BUCKET` | — | Bucket để list (đã có sẵn `_source_bucket()`) |

Thêm vào `validate_ingest_runtime_limits()` ([runtime.py](../../app/interfaces/api/runtime.py)):
khi `STORE_RECONCILE_ENABLED` bật → `interval > 0`, `min_age >= 0`, và `bucket` không rỗng;
thiếu bucket khi bật → raise (fail-closed startup).

### B5. Wiring trong `lifespan`

Trong [runtime.py](../../app/interfaces/api/runtime.py) `lifespan`: tạo task chỉ khi
**bật + parser S3-backed + có source_bucket + có ingest_use_case**. Cancel/await khi shutdown
như `prune_task`/`stale_reaper_task`. Lister build từ cùng nguồn client S3 với parser.

```python
reconciler_task = None
if reconcile_settings.enabled and runtime.source_bucket and runtime.ingest_use_case is not None:
    lister = build_object_store_lister(runtime)   # tái dùng S3 client/creds
    reconciler_task = asyncio.create_task(
        run_store_reconciler(lister, runtime.ingest_use_case, reconcile_settings, logger)
    )
# ... lưu app.state, cancel + await trong finally
```

### B6. Cost guard (CONSTRAINTS checklist #17)

List bucket có chi phí. Giữ interval bảo thủ (≥ 15 phút), log `scanned/enqueued` mỗi sweep để
quan sát, và mặc định tắt. Cân nhắc metric đếm số sweep + số enqueue.

### B7. Test Phần B

| Test | Covers |
|------|--------|
| `parse_object_key`: key hợp lệ / sai prefix / thiếu filename / không có đuôi | B2 |
| `ObjectStoreLister` S3 adapter: phân trang nhiều page (mock boto3 paginator) | B1 |
| reconcile: object không row → enqueue | B3 |
| reconcile skip: COMPLETED / FAILED / DELETED / có active job / object < min_age | B3 + §2 |
| 2 sweep liên tiếp → không double-enqueue (idempotent) | B3 |
| reconcile tắt (`ENABLED=0`) → task không chạy | B5 |

---

## 5. Ràng buộc & doc bắt buộc cập nhật (CONSTRAINTS)

> Đọc [handoff/CONSTRAINTS.md](../handoff/CONSTRAINTS.md) §4 checklist trước khi merge.

- **#12 (luồng input mới):** reconciler là một luồng vào mới **cố ý** (không phải dev tool) →
  document trong [ops/ingest-transport.md](../ops/ingest-transport.md): mô tả reconcile flow,
  nguồn, idempotency.
- **#14 (quyết định Day-0):** ghi quyết định "reconciler safety-net + doc.status best-effort +
  soft-delete tombstone" vào [decide/NEW_REPO_DECISIONS.md](./NEW_REPO_DECISIONS.md).
- **#1 (dependency direction):** `ObjectStoreLister` là capability contract; reconciler loop ở
  use-case/runtime gọi **qua contract**, không import boto3 trực tiếp. Adapter S3 mới ở
  infrastructure.
- **#10 (test race/idempotency):** bắt buộc test 2 sweep idempotent + skip DELETED.
- **#17 (chi phí):** khai báo cost guard cho list bucket.
- **Không đụng pipeline eval gate** (#13): reconciler không đổi parser/splitter/embedding →
  không cần golden-query gate (trừ khi mở rộng đụng vector write).
- Cập nhật [gap/gap7.md](../gap/gap7.md): đánh dấu G7-16 + G7-8 **đóng bằng reconcile**
  (best-effort doc.status chấp nhận có chủ đích).

---

## 6. Thứ tự thực hiện (checklist)

```
PHẦN A — soft-delete (xanh test rồi mới sang B)
 [ ] A0  enum DELETED
 [ ] A1  soft-delete _delete_sync (postgres) + delete (in-memory)   [parity]
 [ ] A2  guard chặn rời DELETED trong update_status (2 backend)
 [ ] A3  sửa G7-15 race guard: None OR DELETED
 [ ] A4  filter DELETED khỏi list_all (2 backend) + edge get_document -> 404
 [ ] A5  ghi docstring create(): DELETED terminal, không revive
 [ ] A6  cập nhật 3 test cũ + test delete-race
 [ ] A7  test mới Phần A
 [ ] ── chạy: pytest tests -q --ignore=tests/e2e  (AI_PROVIDER=offline) ──

PHẦN B — reconciler
 [ ] B1  ObjectStoreLister contract + adapter S3 (tái dùng boto3 client)
 [ ] B2  parse_object_key + constant RAW_PREFIX
 [ ] B3  reconcile_store_once + run_store_reconciler
 [ ] B4  config + validate (opt-in, fail-closed khi thiếu bucket)
 [ ] B5  wiring lifespan (tạo + cancel task)
 [ ] B6  cost guard + log scanned/enqueued
 [ ] B7  test Phần B
 [ ] ── chạy full suite + cập nhật docs (§5) ──
```

**Điểm dễ sai nhất:** A3 (2 đường ghi status đều phải chặn — A2 + A3), A4 (đừng để
`get_by_id` repository tự giấu DELETED, nếu không reconciler mù). Review kỹ 2 chỗ này.

---

## 7. Quyết định còn mở (xác nhận trước/khi làm)

1. **Prune bia mộ DELETED (retention):** chưa làm trong đợt này. Nếu cần sau: thêm pruner
   `DELETE FROM documents WHERE status='deleted' AND created_at < cutoff`, **cutoff phải lớn
   hơn** chu kỳ + độ trễ dọn object (mặc định bảo thủ ~30 ngày) — prune sớm sẽ mở lại lỗ hồi sinh.
2. **Retry FAILED qua reconcile:** mặc định KHÔNG (poison guard). Nếu muốn retry lỗi transient,
   thêm policy "re-enqueue FAILED cũ hơn N giờ" — cân nhắc riêng, không làm mặc định.
3. **Revive trên re-ingest cùng doc_id (A5):** mặc định không hỗ trợ. Chỉ thêm khi có nhu cầu thật.
