# API Keys & Secrets cần thiết

Tài liệu này liệt kê **mọi secret/API key** của hệ thống, trạng thái hiện tại khi chạy local, và hướng dẫn lấy nếu chưa có.

---

## Tóm tắt nhanh

| Key | Trạng thái (local stack) | Bắt buộc? |
|-----|--------------------------|-----------|
| `OPENAI_API_KEY` | ✅ **Đã có** trong `.env` (root) | **Bắt buộc** |
| `JWT_SECRET_KEY` | ✅ **Đã set sẵn** trong `docker-compose.local.yml` | Bắt buộc |
| MinIO creds | ✅ **Hardcode** `minioadmin/minioadmin` (local only) | Bắt buộc |
| `GEMINI_API_KEY` | ⚠️ Chưa có — chỉ cần cho OCR PDF scan | Optional |
| Microsoft SSO | ⚠️ Chưa có — tắt trong local stack | Optional |
| `LANGFUSE_*` | ✅ **Self-host container** — bật sẵn (pk/sk-lf-local-dev) | Optional |
| `NEW_RELIC_LICENSE_KEY` | ⚠️ Đã có trong `docker-compose.yml` prod — APM tắt ở local | Optional |

---

## Chi tiết từng key

### 1. `OPENAI_API_KEY` — **Bắt buộc**

**Dùng cho:** Embedding tài liệu (rag-worker), query embedding (mcp-service), LLM tạo câu trả lời + agent tool-calling (query-service), caption generation khi ingest PDF.

**Trạng thái:** ✅ Đã có trong `.env` ở root repo. `docker-compose.local.yml` đọc tự động qua `${OPENAI_API_KEY}`.

**Hệ quả nếu thiếu:** rag-worker không embed được tài liệu, query-service không gọi LLM → hệ thống không trả lời được.

**Cách lấy nếu cần key mới:**
1. Truy cập [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Tạo key mới → copy
3. Điền vào file `.env` ở root repo:
   ```
   OPENAI_API_KEY=sk-proj-...
   ```

---

### 2. `JWT_SECRET_KEY` — **Bắt buộc**

**Dùng cho:** Ký và verify JWT token — user-service phát hành, document-service + query-service verify locally. Phải dùng **cùng một giá trị** cho tất cả service.

**Trạng thái:** ✅ Set sẵn `local-dev-jwt-secret-change-in-staging-32ch` trong `docker-compose.local.yml`. **Chỉ dùng cho local dev — KHÔNG dùng cho staging/production.**

**Cách generate secret mạnh cho staging/prod:**
```bash
# PowerShell
[System.Convert]::ToBase64String((1..32 | ForEach-Object {[byte](Get-Random -Max 256)}))

# Python
python -c "import secrets; print(secrets.token_hex(32))"

# OpenSSL (Git Bash / WSL)
openssl rand -hex 32
```

---

### 3. MinIO Credentials (thay GCS cho local)

**Dùng cho:** Object storage lưu file tài liệu upload (document-service ghi, rag-worker đọc). Thay thế GCS trong local stack.

**Trạng thái:** ✅ Hardcode `minioadmin` / `minioadmin` trong `docker-compose.local.yml`. Console MinIO tại `http://localhost:9001`.

**Không cần thay đổi cho local dev.**

---

### 4. `GEMINI_API_KEY` — Optional (OCR PDF scan)

**Dùng cho:** OCR trang ảnh trong PDF scan tiếng Việt (rag-worker, chỉ khi file PDF không có text layer). PDF/DOCX thường có sẵn text → không cần Gemini.

**Trạng thái:** ⚠️ Chưa cấu hình. Hệ thống vẫn ingest được file PDF có text layer, DOCX, TXT, XLSX, CSV, PPTX.

**Hệ quả nếu thiếu:** PDF scan (ảnh) sẽ không extract được text → chunk rỗng → không tìm được. PDF có text layer không ảnh hưởng.

**Cách lấy:**
1. Truy cập [console.cloud.google.com](https://console.cloud.google.com)
2. Chọn project → **APIs & Services** → **Credentials**
3. **+ Create Credentials** → **API key**
4. Bật API **Gemini API** (hoặc **Generative Language API**)
5. Điền vào `.env`:
   ```
   GEMINI_API_KEY=AIza...
   ```
6. Trong `docker-compose.local.yml` thêm vào service `rag-worker`:
   ```yaml
   GEMINI_API_KEY: ${GEMINI_API_KEY}
   OCR_API_KEY: ${GEMINI_API_KEY}
   ```

---

### 5. Microsoft SSO — Optional (Azure AD login)

**Dùng cho:** Đăng nhập Microsoft 365 / Azure AD cho nhân viên VinSmartFuture (user-service `/auth/microsoft`).

**Trạng thái:** ⚠️ Chưa cấu hình. Local stack dùng đăng nhập **email + password** qua `/auth/login`.

**Hệ quả nếu thiếu:** Nút "Đăng nhập Microsoft" không hoạt động. Vẫn dùng được toàn bộ hệ thống với tài khoản local.

**Cách lấy:**
1. [Azure Portal](https://portal.azure.com) → **Azure Active Directory** → **App registrations** → **New registration**
2. Redirect URI: `http://localhost:8000/auth/microsoft/callback`
3. Sau khi tạo, copy:
   - `Application (client) ID` → `MICROSOFT_CLIENT_ID`
   - Tạo secret tại **Certificates & secrets** → `MICROSOFT_CLIENT_SECRET`
   - `MICROSOFT_TENANT_ID`: `common` (mọi account) hoặc tenant ID của công ty
4. Điền vào `docker-compose.local.yml` phần `user-service`:
   ```yaml
   MICROSOFT_CLIENT_ID: "..."
   MICROSOFT_CLIENT_SECRET: "..."
   MICROSOFT_TENANT_ID: "common"
   ```

---

### 6. Langfuse — LLM Observability (self-host v3, bật sẵn)

**Dùng cho:** Tracing LLM calls, token cost, latency dashboard — cây trace LangGraph agent
cho từng request của người dùng.

**Trạng thái:** ✅ Self-host **v3 stack** bật sẵn trong `docker-compose.local.yml`.
- UI: `http://localhost:3100` — đăng nhập `admin@local.dev` / `Admin@123456`
- Keys tất định (dev-only): `pk-lf-local-dev` / `sk-lf-local-dev`
- `OBSERVABILITY_MODE=langfuse` đã set trong query-service env
- SDK v4 gửi span qua **OTLP** đến `http://langfuse-web:3000` (nội bộ docker network)

**Stack v3 gồm 4 container mới (tự dựng khi `up`):**

| Container | Image | Vai trò |
|---|---|---|
| `langfuse-web` | `langfuse/langfuse:3` | UI + ingestion API (port 3100) |
| `langfuse-worker` | `langfuse/langfuse-worker:3` | Xử lý span async → ClickHouse |
| `clickhouse` | `clickhouse/clickhouse-server:24` | OLAP store cho trace data |
| `langfuse-redis` | `redis:7-alpine` (noeviction) | BullMQ queue giữa web ↔ worker |

MinIO bucket `langfuse` tạo tự động qua `minio-init`. PostgreSQL `langfuse_db` đã có sẵn.

**Không cần thêm gì để dùng local.** Keys và toàn bộ stack đã có sẵn.

**Nếu muốn dùng Langfuse Cloud (staging/prod):**
1. Truy cập [cloud.langfuse.com](https://cloud.langfuse.com) → tạo project → copy keys.
2. Thay trong `docker-compose.local.yml`:
   ```yaml
   LANGFUSE_PUBLIC_KEY: "pk-lf-..."
   LANGFUSE_SECRET_KEY: "sk-lf-..."
   LANGFUSE_HOST: "https://cloud.langfuse.com"
   ```
   Và xóa/comment block service `langfuse`.

---

### 7. `NEW_RELIC_LICENSE_KEY` — Optional (APM)

**Dùng cho:** Application Performance Monitoring — metrics, traces, errors cho tất cả service.

**Trạng thái:** ⚠️ Key EU đã có trong `docker-compose.yml` (prod), nhưng APM **tắt** (`NEW_RELIC_ENABLED=false`) trong `docker-compose.local.yml` để tránh gửi telemetry ra ngoài khi dev.

**Hệ quả nếu thiếu:** Không có APM dashboard. Không ảnh hưởng chức năng.

**Cách bật (nếu cần):** Xóa dòng `NEW_RELIC_ENABLED: "false"` trong compose local và đảm bảo `NEW_RELIC_LICENSE_KEY` được set.

---

## Checklist trước khi chạy local

- [ ] `OPENAI_API_KEY` có trong `.env` (root repo)
- [ ] Docker Desktop đang chạy
- [ ] Port `80`, `8000-8004`, `4222`, `6333`, `6379`, `9000-9001` chưa bị chiếm
- [ ] *(Optional)* `GEMINI_API_KEY` nếu cần OCR PDF scan
