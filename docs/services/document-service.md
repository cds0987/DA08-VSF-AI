---
service: document-service
path: src/document-service
last-verified: 59551e39 (2026-06-29)
code-refs:
  - src/document-service/app/interfaces/api/main.py
  - src/document-service/app/interfaces/api/routers/documents.py
  - src/document-service/app/interfaces/api/dependencies.py
  - src/document-service/app/core/config.py
  - src/document-service/app/application/use_cases/documents/upload_document_use_case.py
  - src/document-service/app/application/use_cases/documents/common.py
  - src/document-service/app/application/use_cases/documents/get_document_file_use_case.py
  - src/document-service/app/application/use_cases/documents/delete_document_use_case.py
  - src/document-service/app/infrastructure/messaging/nats_publisher.py
  - src/document-service/app/infrastructure/messaging/nats_subscriber.py
  - src/document-service/app/infrastructure/storage/gcs_client.py
  - src/document-service/app/infrastructure/external/hr_department_client.py
  - src/document-service/app/infrastructure/db/models.py
  - src/document-service/Dockerfile
---
# Document Service

FastAPI service quản lý vòng đời tài liệu admin: upload → lưu object storage → phát NATS
cho rag-worker ingest, đồng thời giữ ACL/classification và phục vụ xem file qua presigned URL
hoặc proxy-stream. Chạy uvicorn cổng **8002** (bootstrap qua `newrelic-admin`).

## Trách nhiệm
- Nhận upload (chỉ admin), validate đuôi/size/classification + ACL, lưu vào storage backend.
- Ghi metadata vào Postgres (schema `doc_svc`), phát event `doc.ingest` + `doc.access`.
- Nghe `doc.status` từ rag-worker để cập nhật trạng thái (indexed/failed) + phát `notify.doc_new`.
- Phục vụ list/detail/delete/bulk-delete + audit log; enforce ACL khi xem file.
- Phục vụ xem file: presigned URL, proxy-stream raw, và preview (office→PDF qua Gotenberg).

## API / giao diện
Tất cả dưới prefix `/documents` (trừ `/health`). Auth = JWT Bearer (HS256), department KHÔNG
nằm trong token.
- `POST /documents/upload` — admin; multipart `file` + form `classification`,
  `allowed_departments?`, `allowed_user_ids?`. Trả 202 `{document_id, status, message}`.
- `GET /documents` — admin; query `status?`, `limit` (1–200), `offset`. List + total.
- `GET /documents/supported-formats` — admin; `{extensions[], max_file_bytes}`.
- `GET /documents/audit-logs` — admin; `limit`, `offset` (khai TRƯỚC `/{id}` để khỏi nuốt route).
- `GET /documents/{id}` — user; detail (enforce ACL). 404/403.
- `GET /documents/{id}/file` — user; trả presigned URL GCS (`{url, file_type, expires_in=300}`).
- `GET /documents/{id}/file/preview` — user; nội dung inline render-được; office→PDF Gotenberg
  (cache GCS `previews/`); lỗi convert → 503.
- `GET /documents/{id}/file/raw` — user; proxy-stream bytes qua domain mình (không lộ URL GCS).
- `POST /documents/bulk-delete` — admin; body `{document_ids[]}` → `{deleted, not_found, failed}`.
- `DELETE /documents/{id}` — admin; soft-delete + xoá object + phát `doc.access(deleted=true)`.
- `GET /health` — kiểm tra Postgres + NATS; 503 `degraded` nếu một bên down.

## Luồng nội bộ
1. **Upload**: validate → `storage.upload_file("raw/{doc_id}/{safe_name}")` →
   `repository.create(status=QUEUED)` → publish `doc.ingest` (kèm `gcs_key=gs://...`) +
   `doc.access` → ghi audit `upload`. Publish lỗi sau khi đã lưu → set status FAILED + 503.
2. **Ingest callback**: subscriber nghe `doc.status` (durable `document-service-status`), chỉ
   nhận `indexed`/`failed`, `update_status(chunk_count, error)`; nếu `indexed` → phát
   `notify.doc_new`. ack/nak theo kết quả xử lý.
3. **Delete**: soft-delete DB → phát `doc.access(deleted=true)` → audit → xoá object (best-effort).
   (TODO trong code: chưa có event xoá vector.)
4. **Xem file**: load doc → `with_live_department` (lấy department SỐNG từ hr-service nếu secret +
   non-admin) → `can_access_document` → presigned/stream/preview.

## Config / ENV
- `DOCUMENT_SERVICE_DATABASE_URL` / `DATABASE_URL` (asyncpg).
- `JWT_SECRET_KEY` (bắt buộc, chặn default yếu), `JWT_ALGORITHM` (chỉ HS256).
- `NATS_URL`, `NATS_JETSTREAM_ENABLED` (default true).
- `HR_SERVICE_URL` (default `http://hr-service:8004`) — nguồn department cho ACL secret.
- `STORAGE_BACKEND` = `gcs` (prod) | `s3` (local/MinIO/R2). `GCS_BUCKET`, `GCP_PROJECT_ID`;
  hoặc `S3_BUCKET`/`S3_SOURCE_BUCKET`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`,
  `S3_SECRET_ACCESS_KEY`, `S3_REGION`.
- `GOTENBERG_URL` (default `http://gotenberg:3000`), `GOTENBERG_TIMEOUT_SECONDS` (30).
- `CORS_ORIGINS`, `DOC_ALLOWED_EXTENSIONS` (rỗng = cho tất cả loại rag-worker parse được).
- `MAX_FILE_BYTES` = 50MB (hardcode); `ALLOWED_CLASSIFICATIONS` = public/internal/secret/top_secret.

## ACL / classification
Enforce trong `common.can_access_document`: admin luôn pass; `public` mở; `internal` cần
`account_type=internal`; `secret` cần internal + department (lấy SỐNG từ HR, fail-closed nếu
HR down) ∈ `allowed_departments`; `top_secret` cần `user.id` ∈ `allowed_user_ids`.
Upload bắt buộc `allowed_departments` cho secret, `allowed_user_ids` cho top_secret.

## Phụ thuộc
- **Postgres** (schema `doc_svc`: bảng `documents`, `audit_logs`; Alembic baseline 0001).
- **NATS/JetStream** — stream `DOC_EVENTS` (doc.ingest/doc.status/doc.access),
  `NOTIFY_EVENTS` (notify.doc_new). Event kèm `event_id/event_version/occurred_at`.
- **GCS** (presigned V4; prod keyless → IAM signBlob) hoặc **S3** backend.
- **rag-worker** (consumer doc.ingest, producer doc.status).
- **hr-service** (`GET /hr/employees/departments`, public, cache TTL 30s).
- **Gotenberg** sidecar (office→PDF preview).

## Code map
- [main.py](src/document-service/app/interfaces/api/main.py) — app, lifespan, /health.
- [routers/documents.py](src/document-service/app/interfaces/api/routers/documents.py) — endpoints.
- [dependencies.py](src/document-service/app/interfaces/api/dependencies.py) — DI, JWT auth, require_admin.
- [core/config.py](src/document-service/app/core/config.py) — Settings/ENV.
- [use_cases/documents/upload_document_use_case.py](src/document-service/app/application/use_cases/documents/upload_document_use_case.py)
- [use_cases/documents/common.py](src/document-service/app/application/use_cases/documents/common.py) — ACL + validate.
- [use_cases/documents/get_document_file_use_case.py](src/document-service/app/application/use_cases/documents/get_document_file_use_case.py)
- [use_cases/documents/delete_document_use_case.py](src/document-service/app/application/use_cases/documents/delete_document_use_case.py)
- [messaging/nats_publisher.py](src/document-service/app/infrastructure/messaging/nats_publisher.py)
- [messaging/nats_subscriber.py](src/document-service/app/infrastructure/messaging/nats_subscriber.py)
- [storage/gcs_client.py](src/document-service/app/infrastructure/storage/gcs_client.py)
- [external/hr_department_client.py](src/document-service/app/infrastructure/external/hr_department_client.py)
- [db/models.py](src/document-service/app/infrastructure/db/models.py)
- [Dockerfile](src/document-service/Dockerfile) — uvicorn :8002 qua newrelic-admin.
