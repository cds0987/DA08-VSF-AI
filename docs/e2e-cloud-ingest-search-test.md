# E2E test: document-service → NATS → rag-worker → Qdrant → mcp-service (GCP thật)

Ghi lại lần chạy thử **end-to-end** luồng ingest + search với hạ tầng cloud THẬT
(GCS + Qdrant Cloud + OpenAI), phần stateful (Postgres, NATS) chạy local docker.
Mục tiêu: chứng minh 5 mắt xích `file → S3(GCS) → rag-worker → Qdrant → mcp-search`
hoạt động đúng, KHÔNG cần user-service/query-service.

> Ngày chạy: 2026-06-06. Kết quả: **ingest 9/9 completed, search 6/6 PASS.**

---

## 1. Kiến trúc bài test

```
client (mint JWT admin)
   │  POST /documents/upload (multipart)
   ▼
document-service ──(S3-interop HMAC)──► GCS bucket vsf-rag-chatbot-docs-dev   [THẬT]
   │  publish doc.ingest + doc.access (JetStream)
   ▼
NATS (local, JetStream, stream DOCS auto-create)
   │  doc.ingest
   ▼
rag-worker ── tải file (S3-interop)──► GCS                                    [THẬT]
   │  parse → caption (vision OCR, OpenAI) → embed (OpenAI text-embedding-3-small)
   ▼  upsert vector
Qdrant Cloud  collection rag_chatbot__te3s__d1536 (dim 1536)                  [THẬT]
   ▲  query (embed query → search)
   │
mcp-service  tool rag_search  (Streamable HTTP /mcp)
```

| Thành phần | Môi trường | Ghi chú |
|-----------|-----------|---------|
| GCS bucket `vsf-rag-chatbot-docs-dev` | ☁️ THẬT | truy cập qua **HMAC (S3-interop)**, KHÔNG dùng SA JSON |
| Qdrant Cloud | ☁️ THẬT | đã có contract stamp `fingerprint=0697dee4bb0ac4b8`, dim 1536 |
| OpenAI embeddings/vision | ☁️ THẬT | `text-embedding-3-small` (1536), caption `gpt-4o-mini` |
| Postgres | 🐳 local | doc_db (document-service) + rag_db (rag-worker) |
| NATS JetStream | 🐳 local | stream `DOCS` (`doc.ingest`/`doc.status`/`doc.access`) |
| document-service / rag-worker / mcp-service | 🐳 local build | |

---

## 2. Artifact tạo ra cho bài test

| File | Vai trò |
|------|---------|
| `docker-compose.localtest.yml` (repo root) | Stack đầy đủ: postgres + nats + rag-migrate + rag-worker + document-service + mcp-service. Storage→GCS, vectorDB→Qdrant Cloud (env nhúng). |
| `infra/localtest/init-db.sql` | Tạo `doc_db`, `rag_db`, schema `doc_svc` + bảng `documents`/`audit_logs` (document-service KHÔNG tự `create_all`). |
| `src/document-service/app/infrastructure/storage/s3_client.py` | **S3 storage backend** (boto3) cho document-service — xem §4. |
| Sửa `src/mcp-service/app/main.py` | **Fix bug** khởi động HTTP server — xem §5. |

Tài liệu nguồn: toàn bộ file hợp lệ trong `src/rag-worker/eval/validation/`.

---

## 3. Các bước chạy

```bash
# 0. (sạch môi trường cũ để tránh đụng port)
docker compose -f docker-compose.yml down -v --remove-orphans

# 1. build + up stack
docker compose -f docker-compose.localtest.yml up -d --build

# 2. upload validation files qua document-service (tự mint JWT admin HS256 bằng JWT_SECRET_KEY)
#    POST http://127.0.0.1:8002/documents/upload  (form: file=<bin>, classification=public)

# 3. theo dõi rag-worker ingest
docker logs da08-vsf-rag-worker-1 -f | grep ingest_completed

# 4. kiểm tra Qdrant Cloud
curl -H "api-key: <QDRANT_API_KEY>" \
  "<QDRANT_URL>:6333/collections/rag_chatbot__te3s__d1536"   # -> points_count

# 5. search trực tiếp qua MCP HTTP (client MCP chính thức: initialize -> call_tool rag_search)
#    url = http://mcp-service:8003/mcp
```

**JWT admin tự ký** (không cần user-service): HS256 với `JWT_SECRET_KEY`, payload
`{"sub": "<uuid>", "role": "admin", "exp": <ts>}`. `sub` PHẢI là UUID (cột
`uploaded_by` kiểu UUID).

---

## 4. Vì sao document-service đi qua S3-interop, không phải GCS native

- `gcs_client.py` (native, `google-cloud-storage`) auth bằng **service-account JSON**
  (`GOOGLE_APPLICATION_CREDENTIALS`). DevOps **chưa cấp file JSON** — chỉ có **HMAC key**
  (Access key/Secret) + email SA.
- GCS hỗ trợ truy cập kiểu S3 (`https://storage.googleapis.com` + HMAC). Nên thêm
  `S3StorageClient` ghi vào **cùng bucket GCS** chỉ bằng HMAC.
- Bật bằng env `STORAGE_BACKEND=s3`. Mặc định vẫn `gcs` → KHÔNG đổi hành vi production.
  Khi có SA JSON, bỏ biến này là quay lại native, zero code change.
- `object_uri()` trả `s3://bucket/key`; rag-worker parse được cả `s3://` lẫn `gs://`
  nên cú bắt tay doc-service → rag-worker không đổi.

> Đây chính là nội dung `handoff/document-service-s3-backend.patch` (đã áp tay vì patch
> gốc không apply sạch do `config.py` đã đổi). Thay đổi gồm: `config.py` (+ `STORAGE_BACKEND`,
> `S3_*`), `s3_client.py` (mới), `dependencies.py` (`get_storage` chọn backend),
> `requirements.txt` (+`boto3`).

---

## 5. Bug đã phát hiện & sửa: mcp-service không khởi động được

**Triệu chứng:** container mcp-service crash ngay khi start:
```
TypeError: FastMCP.run() got an unexpected keyword argument 'middleware'
```

**Nguyên nhân:** `app/main.py` gọi
`mcp.run(transport="streamable-http", middleware=...)`, nhưng bản `mcp` SDK đã cài có
`FastMCP.run(self, transport, mount_path)` — **không có `middleware`**. Code còn truyền
kwarg này **mọi lúc** (kể cả khi không bật token) → luôn TypeError → HTTP server không bao
giờ lên → **không thể search qua MCP**.

**Fix:** FastMCP có `streamable_http_app()` trả về Starlette app → gắn middleware bằng
`add_middleware` rồi serve bằng uvicorn:
```python
app = mcp.streamable_http_app()
token = (settings.internal_token or "").strip()
if token:
    app.add_middleware(InternalTokenAuthMiddleware, token=token)
uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())
```
Sau fix: `mcp_contract_verified` + `Uvicorn running on :8003`, tool `rag_search` chạy,
search **6/6 PASS** qua đúng endpoint MCP HTTP.

> Hành động: commit fix này vào mcp-service. `build_mcp_middleware()` trong
> `interfaces/mcp_server.py` giờ không còn được dùng — có thể dọn.

---

## 6. Kết quả

**Ingest** — 9/9 `ingest_completed` (account_reset.txt, emergency_contacts.docx,
fire_evacuation_scanned.pdf, leave_policy.md, onboarding.docx, remote_work_policy.pptx,
security_incident.pdf, travel_per_diem.xlsx, README.md). Qdrant Cloud `points_count` tăng
tương ứng (collection `rag_chatbot__te3s__d1536`, dim 1536).

**Search** — 6/6 golden query trả đúng tài liệu kỳ vọng (qua MCP HTTP `rag_search`):

| Query | Top hit | Keyword |
|-------|---------|---------|
| password reset link expires | account_reset.txt | fifteen ✅ |
| annual leave days full-time | leave_policy.md | twelve ✅ |
| report security incident data breach | security_incident.pdf | breach ✅ |
| days per week work remotely | remote_work_policy.pptx | three ✅ |
| daily meal allowance per diem | travel_per_diem.xlsx | fifty ✅ |
| laptop badge orientation onboarding | onboarding.docx | orientation ✅ |

---

## 7. ⚠️ Những vấn đề cần lưu ý

1. **EMBED_DIMENSION = 1536** (text-embedding-3-small chiều gốc). rag-worker và mcp-service
   PHẢI dùng y hệt — lệch là mcp-service fail-closed. Qdrant Cloud đã chốt 1536; đừng đổi.
   Tên collection vật lý có suffix `__te3s__d1536` do code tự sinh từ model+dimension —
   KHÔNG tạo tay collection tên `rag_chatbot`.

2. **`ALLOWED_EXTENSIONS` của document-service** = `{pdf, docx, txt, xlsx, csv, pptx, md}`.
   File `.html`, `.png`, `.jpg` trong validation **không upload được** qua document-service
   (expense_policy.html, guest_wifi.png, visitor_parking.jpg bị loại) — đúng thiết kế hiện tại.

3. **document-service không tự tạo schema** (`doc_svc.documents`/`audit_logs`) — không có
   `create_all`/alembic. Phải chạy DDL tay (xem `infra/localtest/init-db.sql`). rag-worker
   thì CÓ alembic (`alembic upgrade head` qua service `rag-migrate`).

4. **`doc.status` subscriber của document-service** log
   `NotFoundError` nếu khởi động TRƯỚC khi stream DOCS tồn tại → non-fatal (try/except),
   nhưng khiến doc-service KHÔNG cập nhật trạng thái `indexed`. Khắc phục: start rag-worker
   (tạo stream) trước, hoặc restart document-service sau khi stream sẵn.

5. **Thứ tự khởi động NATS:** rag-worker `NATS_STREAM_AUTO_CREATE=1` tự dựng stream DOCS
   (subjects `doc.ingest`/`doc.status`/`doc.access`). document-service publish JetStream sẽ
   FAIL nếu stream chưa có → upload trả `MessagingPublishError`. Vì vậy compose để
   document-service `depends_on rag-worker`. Production: stream do DevOps provision
   (`infra/nats/jetstream.conf`, tên `DOC_EVENTS`), rag-worker để `AUTO_CREATE=0` verify-only.

6. **Qdrant Cloud:** URL phải có `:6333` + `https`, và BẮT BUỘC `VECTOR_DB_API_KEY`
   (khác hẳn local không cần key). Lúc verify_contract đầu có thể gặp `ConnectTimeout`
   tạm thời → nên thêm retry; hiện restart là qua.

7. **psycopg vs asyncpg:** rag-worker dùng `postgresql+psycopg://` (sync, psycopg v3);
   document-service dùng `postgresql+asyncpg://`. ĐỪNG copy nhầm DATABASE_URL giữa 2 service.

8. **Password Cloud SQL có ký tự đặc biệt** (`@`) phải URL-encode (`%40`) trong DATABASE_URL.
   (Bài test này dùng Postgres local nên không vướng; lưu ý khi chuyển sang Cloud SQL.)

9. **Cloud SQL chặn IP:** kết nối tới Cloud SQL (34.87.63.152) từ ngoài cần IP nằm trong
   Authorized Networks. Bài test này né bằng Postgres local.

10. **Secrets:** compose/test nhúng secret trực tiếp để chạy nhanh → **rotate** sau khi xong
    (OpenAI key, Qdrant key, GitHub token, GCS HMAC).

---

## 8. Dọn dẹp

```bash
docker compose -f docker-compose.localtest.yml down -v
```
Lưu ý Qdrant Cloud là THẬT → vector vẫn còn sau khi `down`. Muốn số liệu sạch, xóa collection
`rag_chatbot__te3s__d1536` (+ `rag_chatbot__meta`) trước khi chạy lại.
