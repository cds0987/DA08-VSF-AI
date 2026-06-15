# Đồng bộ tích hợp: document-service ↔ rag-worker (`doc.ingest` / `doc.status`)

> **Cơ sở so sánh: nhánh `origin/develop`** (đối chiếu code + docs ngày 2026-06-05).
> Mục tiêu: hướng dẫn cụ thể, có code diff, để luồng ingest chạy thông end-to-end:
> Admin upload → `doc.ingest` → rag-worker parse/chunk/embed/index → `doc.status` → document-service cập nhật status.
>
> Source of truth contract: `docs/contracts.md` + `docs/api-spec.md` **trên develop** (đã thống nhất `gcs_key`).
> Đổi contract phải qua SA (xem `docs/contracts.md` §"Quy trình thay đổi contract").

---

## A. Hiện trạng 2 bên trên `develop` — vì sao conflict

### A.1 Contract trên develop (đã thống nhất)

`docs/contracts.md` ([:333,:446](contracts.md)) và `docs/api-spec.md` ([:285](api-spec.md)) trên develop đều ghi field **`gcs_key`**:

```
doc.ingest | { doc_id, gcs_key, file_type, classification, allowed_departments, allowed_user_ids }
```

### A.2 document-service đang làm gì (develop)

- Storage: **S3/MinIO** qua boto3, ENV `AWS_*` ([s3_client.py](../src/document-service/app/infrastructure/storage/s3_client.py)).
- Entity `Document` field `s3_key`, lưu **key tương đối** `raw/{doc_id}/{name}`.
- Publish `doc.ingest` với payload ([upload_document_use_case.py:114-124](../src/document-service/app/application/use_cases/documents/upload_document_use_case.py#L114-L124)):
  `{ doc_id, s3_key, file_type, classification, allowed_departments, allowed_user_ids }`
  → gửi **`s3_key`** (key tương đối), **KHÔNG gửi `document_name`**.
- Subscribe `doc.status`, chỉ chấp nhận `indexed`/`failed`.
- **Không tạo** JetStream stream (chỉ publish).

### A.3 rag-worker đang làm gì (develop)

- Subscribe `doc.ingest`, đọc field **`gcs_key`**, kỳ vọng **URI đầy đủ** (`s3://...`|`gs://...`)
  để parser tự tải ([ingest_consumer.py:52](../src/rag-worker/app/interfaces/nats/ingest_consumer.py#L52)).
- Đọc `document_name` (optional); thiếu → fallback `= doc_id`.
- Bỏ qua `classification`/ACL (đúng thiết kế — query-service mới enforce).
- Storage: ENV **`S3_*`** ([s3_parser.py](../src/rag-worker/app/infrastructure/external/s3_parser.py)).
- **Tự tạo** stream `DOCS` (`ensure_stream("DOCS", ["doc.ingest","doc.status"])`).
- Publish `doc.status` (`indexed`/`failed`) — phần này khớp document-service.

### A.4 Gốc rễ conflict

> Trên develop, **contract đã thống nhất là `gcs_key`** (cả `contracts.md` lẫn `api-spec.md`).
> - **rag-worker code đúng contract** (`gcs_key`, URI đầy đủ).
> - **document-service code KHÔNG khớp contract của chính develop**: publish `s3_key` (key tương đối),
>   thiếu `document_name`. Đây là **lỗi implementation lệch contract**, không phải tranh chấp GCS/S3.
>
> (Ghi chú: branch `nguyendev` còn sửa thêm docs `gcs_key`→`s3_key` cho khớp code sai — đó là divergence
> riêng của branch đó, **không có trên develop**. Trên develop docs vẫn `gcs_key`.)

Năm điểm lệch cùng lúc → ráp vào gãy ngay message đầu:

| # | Điểm lệch | document-service | rag-worker | Bên cần sửa |
|---|---|---|---|---|
| 1 | Field key | `s3_key` | `gcs_key` | document-service |
| 2 | Giá trị key | key tương đối `raw/<id>/<name>` | URI đầy đủ `s3://bucket/...` | document-service |
| 3 | `document_name` | không gửi | có đọc (thiếu → UUID) | document-service |
| 4 | ENV storage | `AWS_*` | `S3_*` | cả hai (DevOps) |
| 5 | Tạo stream `DOCS` | không | có (coupling ordering) | Infra/SA |

### A.5 Hệ quả khi chạy thật (chưa fix)

1. rag-worker đọc `payload["gcs_key"]` → **không có** (gửi `s3_key`) → `BadPayloadError` → `term()` → drop. Document kẹt `queued`.
2. Vá field xong: giá trị là key tương đối → parser cần URI đầy đủ → **không tải được file**.
3. Tải được: `document_name` thiếu → citation hiện **UUID** thay vì tên file.
4. Payload đúng: ENV `AWS_*` vs `S3_*` lệch bucket/endpoint → tải fail.
5. document-service publish khi rag-worker chưa lên (chưa có stream `DOCS`) → `js.publish` lỗi → upload FAILED.

---

## 0. Contract đích (theo develop)

### `doc.ingest` — document-service **publish** → rag-worker **subscribe**

```jsonc
{
  "doc_id": "1f3c...uuid",                           // bắt buộc
  "gcs_key": "s3://rag-chatbot-docs/raw/<id>/a.pdf", // bắt buộc — URI ĐẦY ĐỦ (scheme://bucket/key)
  "file_type": "pdf",                               // bắt buộc — pdf|docx|txt|xlsx|csv|pptx|md
  "document_name": "bao-cao-q1.pdf",                 // BẮT BUỘC — để cite nguồn
  "classification": "internal",                      // metadata — rag-worker BỎ QUA
  "allowed_departments": [],                         // metadata — rag-worker BỎ QUA
  "allowed_user_ids": []                             // metadata — rag-worker BỎ QUA
}
```

> Field tên `gcs_key` nhưng giá trị là URI interop — `s3://...` (MinIO/AWS) hoặc `gs://...` (GCS).
> Parser ([s3_parser.py:31](../src/rag-worker/app/infrastructure/external/s3_parser.py#L31)) nhận cả hai scheme.

### `doc.status` — rag-worker **publish** → document-service **subscribe** (ĐÃ KHỚP, không đổi)

```jsonc
{ "doc_id": "1f3c...", "status": "indexed", "chunk_count": 42 }
{ "doc_id": "1f3c...", "status": "failed",  "error": "parse PDF lỗi: ..." }
```

### `canonical markdown artifact` — rag-worker ghi sau parse/OCR

Luồng production bắt buộc:

```text
GCS raw source -> rag-worker parse/OCR -> canonical Markdown -> GCS artifact -> chunk/caption/embed -> Qdrant
```

- File gốc vẫn nằm ở object `raw/...` do document-service upload.
- Sau khi parse/OCR, rag-worker phải ghi Markdown chuẩn vào GCS: `gs://<S3_SOURCE_BUCKET>/artifacts/<document_id>/markdown.md`.
- Downstream chunk/caption/embed đọc lại chính Markdown artifact này, không index trực tiếp từ buffer tạm.
- Qdrant payload phải giữ cả `source_uri` và `artifact_uri`; mcp-service expose ra client dưới dạng `source_gcs_uri` và `markdown_gcs_uri`.
- `/tmp/artifacts` hoặc `ARTIFACT_ROOT` chỉ là fallback local/dev. Production trên GCP không được coi đó là nguồn bền.

Điều kiện runtime để dùng GCS artifact:

```env
PARSER_IMPL=s3
S3_ENDPOINT_URL=https://storage.googleapis.com
S3_SOURCE_BUCKET=<bucket-name>
```

Checklist khi test 1 tài liệu:

- [ ] Sau `indexed`, GCS có object `artifacts/<document_id>/markdown.md`.
- [ ] Qdrant payload của chunk có `source_uri` và `artifact_uri`.
- [ ] Query/citation trả được URI Markdown artifact qua `markdown_gcs_uri`.
- [ ] Khi delete document, rag-worker xóa vector và artifact Markdown tương ứng.

---

## 1. document-service — code cần sửa

> **🔴 CONFLICT (#1,#2,#3)** — document-service publish `s3_key` (key tương đối), thiếu `document_name`;
> develop contract yêu cầu `gcs_key` (URI đầy đủ) + `document_name`. Bên phải sửa: **document-service**.

### 1.1 Thêm hàm build URI đầy đủ vào storage adapter

`src/document-service/app/infrastructure/storage/s3_client.py` — thêm method (`os` đã import sẵn):

```python
class S3Client:
    # ... giữ nguyên __init__, upload_file, ...

    def object_uri(self, key: str) -> str:
        """URI đầy đủ cho rag-worker tải về. Scheme interop: s3 (MinIO/AWS) | gs (GCS)."""
        scheme = os.getenv("STORAGE_URI_SCHEME", "s3")
        return f"{scheme}://{self.bucket}/{key}"
```

### 1.2 Khai báo method trong Protocol `DocumentStorage`

`src/document-service/app/application/use_cases/documents/upload_document_use_case.py`:

```python
class DocumentStorage(Protocol):
    async def upload_file(self, key: str, content: bytes, content_type: str | None = None) -> None:
        ...

    def object_uri(self, key: str) -> str:   # <-- THÊM
        ...
```

### 1.3 Sửa payload: `s3_key` → `gcs_key` (URI đầy đủ) + thêm `document_name`

Cùng file, trong `execute()` — đoạn `publish_doc_ingest`
([upload_document_use_case.py:114-124](../src/document-service/app/application/use_cases/documents/upload_document_use_case.py#L114-L124)):

```diff
+        gcs_key = self.storage.object_uri(document.s3_key)   # s3://bucket/raw/<id>/<name>
         try:
             await self.publisher.publish_doc_ingest(
                 {
                     "doc_id": document.id,
-                    "s3_key": document.s3_key,
+                    "gcs_key": gcs_key,
                     "file_type": document.file_type,
+                    "document_name": document.name,
                     "classification": document.classification,
                     "allowed_departments": document.allowed_departments,
                     "allowed_user_ids": document.allowed_user_ids,
                 },
             )
```

> Cột `s3_key` trong bảng `documents` giữ nguyên (key tương đối) — chỉ **payload event** đổi sang URI đầy đủ.

### 1.4 Cập nhật test

`tests/unit/test_document_use_cases.py`, `tests/api/test_documents_api.py`:
- Fake storage thêm `object_uri()`.
- Assert payload chứa `gcs_key` (bắt đầu `s3://`) + `document_name`, không còn `s3_key`.

---

## 2. rag-worker — code cần sửa  ✅ ĐÃ XỬ LÝ

> **🟡 CONFLICT (#1)** — rag-worker code **đúng contract develop** (`gcs_key`), không phải bên sai.
> Nó đọc `gcs_key` *cứng* → nếu document-service chưa kịp đổi thì vẫn gãy. Vá nhỏ giúp chấp nhận **cả `s3_key`**
> giai đoạn chuyển, để hai bên không phải deploy đồng thời.
>
> **✅ Đã làm** (branch `nguyendev`): [ingest_consumer.py](../src/rag-worker/app/interfaces/nats/ingest_consumer.py)
> nhận `gcs_key` lẫn `s3_key`; thêm test `test_handle_accepts_s3_key_fallback`. 16/16 test nats pass.

### 2.1 Nhận cả `gcs_key` lẫn `s3_key`

`src/rag-worker/app/interfaces/nats/ingest_consumer.py`, `DocIngestConsumer.handle()`
([ingest_consumer.py:52](../src/rag-worker/app/interfaces/nats/ingest_consumer.py#L52)):

```diff
-        gcs_key = str(payload.get("gcs_key") or "").strip()
+        # Chuẩn develop = gcs_key; chấp nhận s3_key để không gãy khi BE chưa đổi xong.
+        gcs_key = str(payload.get("gcs_key") or payload.get("s3_key") or "").strip()
         file_type = str(payload.get("file_type") or "").strip()
         if not doc_id or not gcs_key or not file_type:
             raise BadPayloadError(
-                "doc.ingest thiếu trường bắt buộc: cần doc_id, gcs_key, file_type"
+                "doc.ingest thiếu trường bắt buộc: cần doc_id, gcs_key (hoặc s3_key), file_type"
             )
```

> `document_name` đã được đọc sẵn (`payload.get("document_name") or doc_id`) — không cần đổi; sau §1.3
> giá trị sẽ là tên file thật thay vì UUID.

### 2.2 `doc.status` — đang đúng, giữ nguyên `build_doc_status()`.

---

## 3. Đồng bộ ENV — credentials phải trỏ CÙNG bucket (BLOCKER ẩn)

> **🔴 CONFLICT (#4)** — document-service đọc `AWS_*`, rag-worker đọc `S3_*`: **hai bộ biến khác tên**.
> Không gì đảm bảo chúng trỏ cùng MinIO/bucket. Hệ quả: payload đúng nhưng rag-worker trỏ **sai endpoint/bucket**
> → tải file fail dù document-service ghi thành công. Lỗi "đúng code vẫn fail" khó debug nhất.

| Ý nghĩa | document-service (`s3_client.py`) | rag-worker (`s3_parser.py`) |
|---|---|---|
| Endpoint | `AWS_S3_ENDPOINT_URL` (mặc định `http://localhost:9000`) | `S3_ENDPOINT_URL` |
| Access key | `AWS_ACCESS_KEY_ID` | `S3_ACCESS_KEY_ID` |
| Secret key | `AWS_SECRET_ACCESS_KEY` | `S3_SECRET_ACCESS_KEY` |
| Region | `AWS_REGION` | `S3_REGION` |
| Bucket | `AWS_S3_BUCKET` (mặc định `rag-chatbot-docs`) | (lấy từ URI trong payload) |

**Phải đảm bảo** (đặt trong docker-compose/.env dùng chung):

```env
# --- chung 1 MinIO/S3 ---
AWS_S3_ENDPOINT_URL=http://minio:9000
S3_ENDPOINT_URL=http://minio:9000
AWS_ACCESS_KEY_ID=minioadmin
S3_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
AWS_REGION=ap-southeast-1
S3_REGION=ap-southeast-1
AWS_S3_BUCKET=rag-chatbot-docs
STORAGE_URI_SCHEME=s3        # document-service build s3://rag-chatbot-docs/...
```

> Bucket `rag-chatbot-docs` phải **tồn tại** trên MinIO trước khi upload (`mc mb` hoặc console).

---

## 4. Đồng bộ NATS / JetStream

| Biến | document-service | rag-worker | Bắt buộc |
|---|---|---|---|
| `NATS_URL` | `nats://nats:4222` | `nats://nats:4222` | **cùng broker** |
| `NATS_JETSTREAM_ENABLED` | `true` | (luôn JetStream) | ép `true` |
| `NATS_STREAM` | — | `DOCS` | |
| `NATS_DOC_INGEST_SUBJECT` | `doc.ingest` (hardcode) | `doc.ingest` | khớp |
| `NATS_DOC_STATUS_SUBJECT` | `doc.status` (hardcode) | `doc.status` | khớp |
| `NATS_DURABLE` | `document-service-status` | `rag-worker-ingest` | khác nhau OK |

Cài lib ở **cả hai**: `pip install nats-py` (import lazy, thiếu thì NATS tắt êm).

### 4.1 Ai tạo stream `DOCS`? (BLOCKER vận hành)

> **🔴 CONFLICT (#5)** — chỉ **rag-worker** tạo stream `DOCS`; **document-service** chỉ publish.
> → coupling thứ tự khởi động ngầm: document-service publish trước khi rag-worker lên (stream chưa có)
> thì `js.publish` lỗi → upload FAILED. Thêm: `doc.access`/`notify.doc_new` document-service publish
> **chưa có stream nào phủ** → cũng lỗi khi JetStream bật.

> **Cập nhật (rag-worker đã đổi):** rag-worker **mặc định KHÔNG còn tự tạo stream** — nó
> `verify_stream` (chỉ kiểm tra stream tồn tại + phủ đủ `doc.ingest,doc.status,doc.access`,
> thiếu → degrade + log ERROR). Dev/CI muốn tự dựng: đặt `NATS_STREAM_AUTO_CREATE=1`.
> → Việc tạo stream giờ thuộc **Infra/SA** (init script bên dưới); document-service vẫn chỉ publish.

**Cách chốt**: tạo stream bằng init script độc lập, chạy trước cả 2 service:

```bash
# infra/nats/init-streams.sh — chạy 1 lần khi dựng hạ tầng.
# Layout chuẩn (tên + retention) là infra/nats/jetstream.conf — dùng đó làm nguồn sự thật.
nats --server "$NATS_URL" stream add DOC_EVENTS \
  --subjects "doc.ingest,doc.status,doc.access" \
  --storage file --retention limits --max-age 7d --dupe-window 2m --defaults

# notify.doc_new do document-service publish (cho query-service)
nats --server "$NATS_URL" stream add NOTIFY_EVENTS \
  --subjects "notify.doc_new" \
  --storage file --retention limits --max-age 3d --dupe-window 2m --defaults
```

> Không có `doc.delete`: xóa vector đi qua `doc.access{deleted:true}` (xem §4b).

### 4.2 Trạng thái `processing` (dọn sau MVP)

> **🟡 CONFLICT** — rag-worker **không bao giờ phát** `processing` (chỉ `indexed`/`failed`), còn
> document-service subscriber **reject** mọi status khác → `nak` → **redeliver vô hạn** nếu lỡ nhận `processing`
> ([nats_subscriber.py:68-70](../src/document-service/app/infrastructure/messaging/nats_subscriber.py#L68-L70)).
> Hai bên đang "vô tình khớp" do cùng né `processing`, nhưng là quả bom hẹn giờ.

Chốt 1 trong 2:
- **(a) bỏ `processing` khỏi luồng** — đủ cho MVP, document chuyển `queued`→`indexed` thẳng. *(khuyến nghị)*
- (b) rag-worker phát `processing` khi bắt đầu + document-service `update_status(PROCESSING)` thay vì reject.

---

## 4b. Luồng DELETE — vector orphan ✅ ĐÃ GIẢI QUYẾT (qua `doc.access`)

> **Bối cảnh (#8)** — Admin xóa tài liệu nhưng vector trong Qdrant không bị xóa → search vẫn
> trả chunk đã xóa (kết quả cũ + **rò rỉ nội dung secret/top_secret**). Đã đóng bằng cách
> **tái dùng `doc.access{deleted:true}`** làm tín hiệu xóa — KHÔNG thêm subject mới `doc.delete`.

### Quyết định: xóa đi qua `doc.access{deleted:true}` — `doc.delete` đã LOẠI BỎ

Contract chính thức ([infra/nats/subjects.md](../infra/nats/subjects.md)) **không có** `doc.delete`. document-service
lúc xóa đã publish `doc.access{deleted:true}` (vốn để query-service cập nhật ACL projection). rag-worker
**dùng chính event này** làm tín hiệu xóa vector → không cần document-service thêm publisher mới, không cần
ratify subject mới.

```jsonc
// document-service publish (đã có sẵn) → rag-worker subscribe
{ "doc_id": "1f3c...uuid", "classification": "...", "allowed_departments": [], "allowed_user_ids": [], "deleted": true }
```

### Hiện trạng (đã thông 2 đầu)

| | document-service | rag-worker |
|---|---|---|
| Khi delete | xóa S3 + DB record + publish `doc.access {deleted:true}` | — |
| Capability xóa vector | — | ✅ `IngestDocumentUseCase.delete()` → `vectors.delete_by_document` + `documents.delete` (idempotent) |
| Đường kích hoạt | ✅ event `doc.access{deleted:true}` | ✅ `DocAccessDeleteConsumer` + `start_doc_access_subscription` (durable `rag-worker-access`) |

**rag-worker** ✅ **ĐÃ LÀM**:
- [ingest_consumer.py](../src/rag-worker/app/interfaces/nats/ingest_consumer.py): `DocAccessDeleteConsumer`
  (chỉ xử lý khi `deleted=true`, bỏ qua upload; tái dùng `use_case.delete()`) + `start_doc_access_subscription`
  (ack cả khi bỏ qua lẫn khi xóa xong; term payload hỏng; nak lỗi tạm).
- [runtime.py](../src/rag-worker/app/interfaces/api/runtime.py): subscribe `doc.access` (durable `rag-worker-access`),
  verify/ensure stream phủ `doc.access`, teardown khi shutdown.
- ENV: `NATS_DOC_ACCESS_SUBJECT=doc.access`, `NATS_ACCESS_DURABLE=rag-worker-access`.

> **`doc.delete` đã được GỠ HẲN khỏi rag-worker** (class `DocDeleteConsumer`, `start_doc_delete_subscription`,
> cfg `doc_delete_subject`/`delete_durable`, test liên quan) — vì nó không có trong contract và không ai publish.
> Nếu sau này cần subject xóa riêng, phải ratify vào `subjects.md` trước (SA), rồi mới khôi phục consumer.

---

## 5. Runbook chạy & kiểm tra end-to-end

### 5.1 Khởi động (đúng thứ tự)

```bash
docker compose up -d nats minio postgres
bash infra/nats/init-streams.sh          # tạo stream DOCS + ACCESS
mc mb local/rag-chatbot-docs             # tạo bucket (nếu chưa có)

docker compose up -d rag-worker          # log mong đợi: nats_ingest_started stream=DOCS
docker compose up -d document-service
```

### 5.2 Bắn thử 1 tài liệu

```bash
TOKEN=$(curl -s localhost:8001/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@corp.com","password":"..."}' | jq -r .access_token)

curl -s -X POST localhost:8002/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F 'file=@./bao-cao-q1.pdf' -F 'classification=internal'
# kỳ vọng: 202 { "document_id": "...", "status": "queued" }
```

### 5.3 Theo dõi log

| Service | Log mong đợi |
|---|---|
| rag-worker | `doc_ingest_enqueued doc_id=<id>` → (worker xử lý) → publish `doc.status` |
| document-service | nhận `doc.status` → `update_status(<id>, indexed, chunk_count=N)` |

```bash
curl -s localhost:8002/documents/<id> -H "Authorization: Bearer $TOKEN" | jq
# kỳ vọng: { "status": "indexed", "chunk_count": N>0, ... }
```

### 5.4 Tiêu chí "chạy được" ✅

- [ ] Upload → document tự chuyển `queued` → `indexed`.
- [ ] `chunk_count > 0`, khớp số chunk thực.
- [ ] File hỏng → `failed` + `error`, không kẹt `queued`.
- [ ] Citation (qua query-service) hiển thị **tên file thật**, không phải UUID.
- [ ] Kill rag-worker giữa chừng rồi bật lại → `doc.ingest` không mất (JetStream redeliver).
- [ ] rag-worker đọc được file từ cùng bucket document-service ghi (ENV §3 đúng).

---

## 6. Checklist & thứ tự ưu tiên

| # | Việc | Bên | Mức | Mục |
|---|---|---|---|---|
| 1 | `s3_key`→`gcs_key` + URI đầy đủ + `document_name` | document-service | 🔴 Blocker | §1 |
| 2 | Nhận `gcs_key` lẫn `s3_key` | rag-worker | 🔴 Blocker | §2.1 |
| 3 | ENV `AWS_*`/`S3_*` cùng bucket/endpoint | cả hai (DevOps) | 🔴 Blocker | §3 |
| 4 | Tạo stream `DOC_EVENTS` + `NOTIFY_EVENTS` bằng init script | Infra/SA | 🔴 Blocker | §4.1 |
| 5 | ✅ Luồng DELETE qua `doc.access{deleted:true}` (vector orphan đã đóng; `doc.delete` đã gỡ) | rag-worker | ✅ Done | §4b |
| 6 | Ép `NATS_JETSTREAM_ENABLED=true` | document-service | 🟡 | §4 |
| 7 | Chốt/bỏ `processing` | cả hai + SA | 🟡 Sau MVP | §4.2 |
| 8 | Cập nhật unit/api test | cả hai | 🟡 | §1.4, §2 |

**MVP chạy được = hoàn thành #1–#4.** Phần lớn việc nằm ở **document-service** (lệch contract develop);
rag-worker chỉ cần 1 vá nhỏ tương thích ngược.
