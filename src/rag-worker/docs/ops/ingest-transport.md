# Ingest transport: NATS `doc.ingest` + nguồn S3/GCS

> Trạng thái: **đã thực thi + verify e2e THẬT trong CI** (NATS JetStream + MinIO + Qdrant
> dựng bằng docker; `tests/e2e/test_nats_protocol_e2e.py` chạy luồng thật, không mock phía
> rag-worker). Đã thêm consumer `doc.delete` (xóa vector). Bug S3 client gặp khi e2e thật:
> [s3-client-botocore.md](s3-client-botocore.md). Thiết kế nền: [../decide/technique/ingestion.md](../decide/technique/ingestion.md);
> wiring khai báo: [../refactor/config-driven-pipeline.md](../refactor/config-driven-pipeline.md).

## 0. Tóm tắt

Tạo-ingest đi qua **NATS JetStream** (không còn `POST /ingest` HTTP). File nguồn lấy
từ **S3/GCS** bằng `source_uri` — `rag-worker` tự tải an toàn. Search vẫn là **HTTP**.

```
BE publish  doc.ingest {doc_id, gcs_key, file_type, ...}
   → rag-worker subscribe (JetStream durable consumer)
   → map gcs_key → source_uri, enqueue vào job-queue DB (lease/retry như cũ)  → ack
   → worker xử lý: fetch S3 → parse → chunk → embed → upsert Qdrant
   → publish  doc.status {doc_id, status: indexed|failed, chunk_count|error}
```

## 1. NATS ingest (Cách A — đẩy vào job-queue DB sẵn có)

Consumer **chỉ làm việc nhẹ**: nhận message → `enqueue` vào hàng đợi DB → ack. Phần
nặng (parse/embed/upsert) do worker DB xử lý — tái dùng nguyên độ bền đã có (atomic
claim, lease/heartbeat, stale-reaper, retry) thay vì dựa hoàn toàn vào JetStream.

**Subject & contract** (khớp [docs/api-spec.md](../../../../docs/api-spec.md)):

| Subject | Hướng | Payload |
|---|---|---|
| `doc.ingest` | Subscribe | `{ doc_id, gcs_key, file_type, document_name?, classification?, allowed_departments?, allowed_user_ids? }` |
| `doc.status` | Publish | `{ doc_id, status: "indexed"\|"failed", chunk_count?, error? }` |

**Map payload → enqueue** ([app/interfaces/nats/ingest_consumer.py](../../app/interfaces/nats/ingest_consumer.py)):
- `doc_id` → `document_id` (danh tính + chunk_id + idempotency)
- `gcs_key` → `source_uri` (địa chỉ object `s3://…`/`gs://…`; PARSER_IMPL=s3 tự tải)
- `classification`/ACL: **metadata thụ động, rag-worker KHÔNG enforce** (caller tầng
  trên tự lọc — [search.md §6](../decide/technique/search.md)) → hiện bỏ qua khi ingest.

**Ack semantics** (đảm bảo at-least-once + không kẹt poison message):

| Tình huống | Hành động | Vì sao |
|---|---|---|
| enqueue OK | `ack` | message an toàn trong DB queue |
| payload hỏng (thiếu field / JSON sai → `BadPayloadError`) | `term` | poison → KHÔNG redeliver vô hạn |
| lỗi tạm (DB down…) | `nak` | JetStream gửi lại để retry |

> Độ bền hai lớp: JetStream giữ message tới khi ack; DB job-queue giữ job tới khi xử lý xong.

**Idempotency / redelivery.** JetStream là at-least-once → có thể gửi lại `doc.ingest`.
`enqueue` **dedup**: nếu đã có job chưa-terminal (pending/processing/stale) cho cùng
`document_id` thì bỏ qua, không tạo job mới (tránh re-fetch S3 + parse + embed dư và
hai worker chạy song song). Check này phủ redelivery phổ biến (redeliver tới SAU khi
job đầu đã vào DB). Race đồng-thời hiếm vẫn vô hại: `chunk_id` deterministic + upsert
OVERWRITE → ghi đè cùng vector. **Khử trùng tuyệt đối cross-process cần unique partial
index** trên `document_id WHERE status non-terminal — TODO** ([ingestion.md §7](../decide/technique/ingestion.md)).

**Trạng thái terminal:** job lỗi → `process_next_job` trả job FAILED (KHÔNG raise) →
worker publish `doc.status: failed`. Job thành công → `indexed`. (Trước đây nhánh FAILED
bị nuốt ở worker → BE không nhận được failed; đã sửa.)

**doc.status là best-effort.** `publish_for_job` nuốt lỗi publish (chỉ log) để không
làm sập worker. Nếu NATS chớp tắt đúng lúc publish → BE **mất tín hiệu** indexed/failed,
hiện CHƯA retry/outbox. Giới hạn đã biết → cân nhắc outbox/re-publish khi cần handshake
chắc chắn (xem §6).

## 2. Nguồn S3/GCS (`PARSER_IMPL=s3`)

BE chỉ gửi `gcs_key`; `rag-worker` tự tải. Parser `s3`
([app/infrastructure/external/s3_parser.py](../../app/infrastructure/external/s3_parser.py))
tải an toàn rồi giao bản local cho `LocalFileParser` (không đổi logic OCR/format);
lineage giữ URL gốc. Hỗ trợ GCS (S3-interop), R2, MinIO, AWS qua boto3.

**5 lớp chống sập server khi tải:**

| Lớp | Cơ chế |
|---|---|
| 1. HEAD trước khi tải | quá `MAX_REMOTE_SOURCE_BYTES` → từ chối ngay, không tải |
| 2. Stream xuống đĩa | không nạp cả file vào RAM (chống OOM) |
| 3. Chặn cứng khi tải | đếm byte, vượt ngưỡng → hủy + xóa (phòng HEAD sai) |
| 4. Semaphore | `S3_FETCH_CONCURRENCY` giới hạn tải đồng thời (chống đầy đĩa) |
| 5. Timeout + dọn rác | connect/read timeout; luôn xóa file tạm trong `finally` |

## 3. Đăng ký qua registry (không sửa engine)

Parser `s3` cắm qua `register_parser("s3", …)`; mọi component tháo-lắp dùng chung
primitive [core_engine/registry.py](../../core_engine/registry.py) (register/get +
entry-point discovery `rag_worker.<component>` cho plugin bên thứ ba). Đổi parser =
đổi `PARSER_IMPL`, KHÔNG sửa use-case/engine (hexagonal).

## 4. Cấu hình (env)

```bash
# Bật NATS ingest (không set NATS_URL -> tắt; HTTP search vẫn chạy). Cần: pip install nats-py
NATS_URL=nats://nats:4222
NATS_STREAM=DOCS
NATS_DOC_INGEST_SUBJECT=doc.ingest
NATS_DOC_STATUS_SUBJECT=doc.status
NATS_DURABLE=rag-worker-ingest    # durable push consumer (1 subscription/process)

# Tải nguồn từ GCS (S3-interop). Cần: pip install boto3
PARSER_IMPL=s3
S3_ENDPOINT_URL=https://storage.googleapis.com    # GCS; R2/AWS thì khác/trống
S3_ACCESS_KEY_ID=<hmac-key>
S3_SECRET_ACCESS_KEY=<hmac-secret>
MAX_REMOTE_SOURCE_BYTES=10485760                  # trần 1 file (10MB)
S3_FETCH_CONCURRENCY=4                             # số file tải đồng thời
```

Secret chỉ ở `.env` (gitignored), không vào `config.yaml`. Đầy đủ biến: [.env.example](../../.env.example).

## 5. Test

**Unit (luôn chạy, không cần NATS)** — broker/S3 giả: map payload, ack/nak/term,
publish status, size-guard/stream-cap/dọn rác. Toàn bộ suite xanh offline.

**Integration NATS thật (opt-in)** — [tests/e2e/test_nats_ingest.py](../../tests/e2e/test_nats_ingest.py)
chứng minh phần transport thật (connect → ensure_stream → durable subscribe → ack;
doc.status round-trip). Tự **skip nếu chưa set `NATS_URL`**.

- **Trong CI** ([.github/workflows/rag-service-ci.yml](../../../../.github/workflows/rag-service-ci.yml)):
  runner dựng NATS JetStream bằng `docker run nats:2.10 -js`, set `NATS_URL` →
  test chạy thật mỗi PR. **Đây là cách verify NATS — không cần docker ở máy dev.**
- **Local** (nếu muốn): tải `nats-server` (1 binary), rồi
  `nats-server -js` + `NATS_URL=nats://localhost:4222 pytest tests/e2e/test_nats_ingest.py`.

## 6. Việc còn lại / giới hạn đã biết

- **doc.status best-effort → outbox.** Publish lỗi hiện chỉ log (best-effort), trong
  khi ingest durable → bất đối xứng độ tin cậy. Cần **outbox/re-publish** nếu BE phụ
  thuộc tuyệt đối vào handshake status.
- **Dedup tuyệt đối cross-process** cần unique partial index trên `document_id` (status
  non-terminal); hiện là check-then-insert + chunk_id deterministic (đủ cho redelivery
  thường, race hiếm vô hại).
- **Multi-replica:** durable-only push = 1 subscription/process; scale ngang nhiều
  replica cần deliver-group hoặc pull consumer.
- **`INGEST_WORKER_COUNT=0` + NATS bật:** message được enqueue nhưng không worker xử
  lý → không publish status (startup log WARNING `nats_ingest_without_worker`).
- **NATS hỏng lúc startup → degrade:** `start_nats_ingest` đóng broker + log ERROR
  `nats_ingest_start_failed`, service vẫn boot (search/HTTP chạy), ingest tắt.
- ⚠️ **Smoke-test toàn trình production** (publish `doc.ingest` thật → Qdrant có
  vector → nhận `doc.status`) cần DevOps dựng NATS bền + Qdrant + Postgres; chi tiết
  hạ tầng ở [deploy/CI-CD.md](../../deploy/CI-CD.md). `infra/nats/jetstream.conf` còn stub.
- Chưa làm: `rag.search` request-reply qua NATS (search vẫn HTTP theo yêu cầu hiện
  tại); change-detector/reconciliation scanner ([ingestion.md §1 ★](../decide/technique/ingestion.md)).
