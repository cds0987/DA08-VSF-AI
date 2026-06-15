# Hướng dẫn chạy và sử dụng hệ thống RAG Chatbot — Local

> ⚠️ **ĐÃ THAY THẾ (2026-06-12):** `docker-compose.local.yml` đã bị xóa. Stack chạy cục bộ
> chuẩn giờ là **`docker-compose.e2e.yml`** (GCS + Qdrant Cloud thật, cần `.env` với
> `OPENAI_API_KEY`/`QDRANT_URL`/`QDRANT_API_KEY`/`GCS_HMAC_*`) — xem
> [`infra/e2e/README.md`](../../../infra/e2e/README.md). Thay mọi `docker-compose.local.yml`
> dưới đây bằng `docker-compose.e2e.yml`.

## Yêu cầu trước khi bắt đầu

| Công cụ | Phiên bản | Lưu ý |
|---------|-----------|-------|
| Docker Desktop | ≥ 4.x | Bật và đang chạy |
| Git | Latest | Clone repo |
| `OPENAI_API_KEY` | — | Điền vào file `.env` (xem bước 1) |

**Port cần trống:** `80`, `8000`, `8001`, `8002`, `8003`, `8004`, `4222`, `6333`, `6379`, `9000`, `9001`

---

## Bước 1 — Chuẩn bị `.env`

Tạo file `.env` ở **root repo** (nếu chưa có):

```
OPENAI_API_KEY=sk-proj-...
```

`docker-compose.local.yml` đọc biến này tự động. Các key khác (MinIO, JWT dev) đã được set sẵn trong compose.

> Xem toàn bộ danh sách key tại [`docs/key-need.md`](key-need.md).

---

## Bước 2 — Build và start toàn bộ stack

```powershell
# Từ thư mục root repo
docker compose -f docker-compose.local.yml up -d --build
```

**Lần đầu:** build tất cả image từ source (~10–15 phút tùy máy). Các lần sau nhanh hơn nhiều.

**Thứ tự khởi động tự động:**
1. Infra: `postgres`, `redis`, `qdrant`, `nats`, `minio`
2. Init: `minio-init` (tạo bucket), `query-migrate` (versioned SQL), `rag-migrate` + `hr-migrate` (Alembic)
3. Backend: `user-service`, `document-service`, `hr-service`, `rag-worker`
4. `mcp-service` (xem lưu ý bên dưới), `query-service`
5. Frontend: `frontend-chat`, `frontend-admin`, `nginx`

> ⚠️ **mcp-service crash-loop lúc đầu là bình thường.** Service này verify Qdrant collection tồn tại khi boot. Collection chỉ được tạo sau lần ingest tài liệu đầu tiên. Sau khi upload xong tài liệu (Bước 5), mcp-service tự restart và khỏe. Không cần can thiệp.

---

## Bước 3 — Kiểm tra trạng thái

```powershell
# Xem tất cả container
docker compose -f docker-compose.local.yml ps

# Xem log service cụ thể
docker compose -f docker-compose.local.yml logs -f query-service
docker compose -f docker-compose.local.yml logs -f rag-worker
docker compose -f docker-compose.local.yml logs -f mcp-service
```

Khi ổn định: các one-shot (`query-migrate`, `rag-migrate`, `hr-migrate`, `minio-init`) ở `Exited (0)`, các service khác `Up`. Migration lỗi sẽ chặn query-service khởi động.

---

## Bước 4 — Tạo tài khoản admin

User-service cần ít nhất 1 tài khoản admin để đăng nhập Admin Console và upload tài liệu.

**Cách 1 — Qua Swagger UI:**
1. Mở `http://localhost:8000/docs`
2. Endpoint `POST /auth/register` → điền:
   ```json
   {
     "email": "admin@local.dev",
     "password": "Admin@123456",
     "role": "admin",
     "department": "it"
   }
   ```
3. Click **Execute** → status `201 Created`

**Cách 2 — Curl (PowerShell):**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/auth/register" `
  -Method Post -ContentType "application/json" `
  -Body '{"email":"admin@local.dev","password":"Admin@123456","role":"admin","department":"it"}'
```

---

## Bước 5 — Đăng nhập và upload tài liệu

### 5a. Đăng nhập Admin Console

1. Mở **`http://localhost/admin`** (qua nginx)
2. Đăng nhập với tài khoản vừa tạo ở Bước 4

### 5b. Upload tài liệu

1. Vào **Documents** → **Upload**
2. Chọn file (`.pdf`, `.docx`, `.txt`, `.xlsx`, `.csv`, `.pptx`)
3. Chọn **Classification** (public / internal / confidential)
4. Click **Upload** → status chuyển sang `queued` → `processing` → `ready`

**Theo dõi tiến trình ingest:**
```powershell
docker compose -f docker-compose.local.yml logs -f rag-worker
# Tìm dòng: ingest_completed, chunk_count, embed_completed
```

### 5c. mcp-service tự khỏe

Sau khi ingest xong, `mcp-service` verify collection thành công và start lại lần cuối:
```powershell
docker compose -f docker-compose.local.yml logs mcp-service | Select-String "contract_verified|Uvicorn running"
```

---

## Bước 6 — Trò chuyện với chatbot

1. Mở **`http://localhost`** (Chat App — End User)
2. Đăng nhập (tài khoản `user` user@local.dev User@123456)
3. Gõ câu hỏi liên quan tài liệu đã upload
4. Nhận câu trả lời **có citation** (tên file, đoạn trích dẫn)

> **Chat App** dành cho End User — chỉ thấy chat + notification.
> **Admin Console** (`/admin`) dành cho Admin — quản lý tài liệu, user, xem metrics.

---

## Bảng URL địa chỉ truy cập

| Dịch vụ | URL | Mô tả |
|---------|-----|-------|
| **Chat App** | `http://localhost` | Giao diện chat cho End User |
| **Admin Console** | `http://localhost/admin` | Quản lý tài liệu, user, metrics |
| **Langfuse UI** | `http://localhost:3100` | LLM trace/observability (admin@local.dev / Admin@123456) |
| User Service Docs | `http://localhost:8000/docs` | Swagger — Auth, User management |
| Query Service Docs | `http://localhost:8001/docs` | Swagger — Chat, Conversations |
| Document Service Docs | `http://localhost:8002/docs` | Swagger — Upload, Documents |
| HR Service Docs | `http://localhost:8004/docs` | Swagger — Employee data (internal) |
| MinIO Console | `http://localhost:9001` | Object storage UI (admin: `minioadmin/minioadmin`) |
| NATS Monitoring | `http://localhost:8222` | NATS JetStream metrics |

> **mcp-service** (`:8003`) là MCP endpoint — truy cập qua `http://localhost:8003/mcp` bằng MCP client; `http://localhost:8003/health` cho healthcheck.

---

## Lệnh thường dùng

```powershell
# Start (đã build)
docker compose -f docker-compose.local.yml up -d

# Stop (giữ data)
docker compose -f docker-compose.local.yml down

# Stop và xóa toàn bộ data (reset sạch)
docker compose -f docker-compose.local.yml down -v

# Rebuild 1 service cụ thể (sau khi sửa code)
docker compose -f docker-compose.local.yml up -d --build query-service

# Rebuild toàn bộ
docker compose -f docker-compose.local.yml up -d --build

# Xem log realtime
docker compose -f docker-compose.local.yml logs -f <service-name>

# Kiểm tra trạng thái nhanh
docker compose -f docker-compose.local.yml ps
```

---

## Luồng hoạt động end-to-end

```
Admin upload tài liệu (PDF/DOCX/...)
    ↓ document-service lưu file vào MinIO + publish NATS doc.ingest
    ↓ rag-worker nhận, tải từ MinIO, parse → chunk → embed (OpenAI) → lưu Qdrant
    ↓ mcp-service verify collection → khỏe
    ↓
User hỏi câu (Chat App)
    ↓ query-service nhận, LangGraph agent quyết định dùng tool rag_search
    ↓ mcp-service embed query (OpenAI) → search Qdrant → rerank → trả kết quả
    ↓ query-service dùng GPT-4o-mini tổng hợp câu trả lời + citation
    ↓ Trả lời SSE stream về trình duyệt
```

---

## Troubleshooting

| Triệu chứng | Nguyên nhân | Cách xử lý |
|-------------|-------------|------------|
| `OPENAI_API_KEY` missing khi up | Chưa điền `.env` | Tạo `.env` với `OPENAI_API_KEY=sk-...` ở root repo |
| Containers không start, port bị chiếm | Port đang dùng | `netstat -ano | findstr :80` → kill process hoặc đổi port trong compose |
| mcp-service liên tục restart | Chưa có tài liệu nào được ingest | Bình thường — upload tài liệu (Bước 5) rồi đợi ingest xong |
| Login trả 401 "Invalid signature" | `JWT_SECRET_KEY` lệch giữa services | Kiểm tra tất cả service dùng cùng key trong compose |
| Document upload trả 401 | JWT expired hoặc sai | Đăng nhập lại để lấy token mới |
| Document upload trả 500 | MinIO chưa sẵn / bucket chưa tạo | Kiểm tra `docker compose logs minio-init` — phải `Exited (0)` |
| rag-worker không ingest, log `S3 NoSuchBucket` | S3_SOURCE_BUCKET không khớp | Đảm bảo bucket `vsf-rag-chatbot-docs-dev` đã tạo: `docker compose logs minio-init` |
| Chat trả lời "no context" / không có citation | mcp-service chưa khỏe hoặc chưa có tài liệu | Kiểm tra `docker compose logs mcp-service` |
| Frontend trắng / 502 | Nginx khởi động trước frontend | Đợi thêm 30s rồi refresh, hoặc `docker compose restart nginx` |
| `postgres: FATAL: database "rag_db" does not exist` | Volume postgres cũ từ lần chạy trước (version mismatch) | `docker compose down -v` để xóa volume → up lại |

---

## Reset hoàn toàn

```powershell
# Xóa tất cả containers + volumes (mất data tài liệu đã upload + vector)
docker compose -f docker-compose.local.yml down -v

# Build lại từ đầu
docker compose -f docker-compose.local.yml up -d --build
```

---

## Tài liệu tham khảo thêm

| File | Dành cho |
|------|---------|
| [`docs/track.md`](track.md) | **Theo dõi luồng & bắt lỗi** — correlation ID, Langfuse, health check, triệu chứng thường gặp |
| [`docs/key-need.md`](key-need.md) | Danh sách API keys, trạng thái, cách lấy |
| [`docs/env-setup.md`](env-setup.md) | Chi tiết biến môi trường từng service |
| [`docs/api-spec.md`](api-spec.md) | HTTP endpoints đầy đủ |
| [`docs/architecture.md`](architecture.md) | Kiến trúc Clean Architecture 4 layer |
| [`infra/localtest/README.md`](../infra/localtest/README.md) | Runbook test e2e với cloud thật (GCS + Qdrant Cloud) |
