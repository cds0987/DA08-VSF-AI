# Code Review — Intern Services
> **Branch:** develop → main  
> **Date:** 2026-06-06  
> **Reviewer:** Claude Code (automated multi-agent review)

---

## Tổng quan kiến trúc

Tất cả 4 service đều theo **Clean Architecture / DDD** (domain → application → infrastructure), dùng Protocol injection — rất tốt cho intern-level work. Dưới đây là đánh giá chi tiết từng service.

---

## 1. `user-service`

### Điểm mạnh
- Refresh token rotation đúng chuẩn: lưu hash (bcrypt), revoke token cũ khi issue mới
- Không có SQL injection: toàn bộ DB access qua SQLAlchemy ORM
- Brute-force lockout được implement đúng (increment counter, `locked_until`)
- bcrypt usage chuẩn, không tái sử dụng salt
- Clean architecture boundary rõ ràng, testable

### Cần cải thiện

| Mức độ | File:Line | Vấn đề |
|--------|-----------|--------|
| 🔴 CRITICAL | `app/application/use_cases/auth/login_use_case.py:99` | Thiếu `return`/`raise` sau `_handle_failed_password()` — nếu helper bị refactor thành non-raising, sẽ login thành công với **mật khẩu sai** |
| 🔴 CRITICAL | `app/core/config.py:20` | JWT secret mặc định là `"change-me-in-env"` — nếu deploy thiếu env var, attacker mint được JWT hợp lệ cho bất kỳ user nào |
| 🟠 HIGH | `app/infrastructure/security/jwt_token_service.py:11` | Access token TTL = **480 phút (8 giờ)**, không có JTI blocklist → token bị đánh cắp valid suốt 8 giờ dù user bị deactivate |
| 🟠 HIGH | `app/infrastructure/db/postgres_user_repository.py:67` | `list_all` return `list[User \| None]` nhưng type hint là `list[User]` → `AttributeError` tiềm ẩn |
| 🟡 MEDIUM | `app/interfaces/api/dependencies.py:105` | Không catch `json.JSONDecodeError` khi body malformed → trả 500 thay vì 422 |
| 🟡 MEDIUM | `app/application/use_cases/auth/refresh_token_use_case.py:56` | Split token không validate UUID format → `ValueError` từ `UUID()` trong repo = unhandled 500 |
| 🟡 MEDIUM | `app/core/config.py:20` | `get_settings()` được cache bằng `@lru_cache` nhưng không validate `jwt_secret_key != "change-me-in-env"` tại startup — service start thành công với weak key |
| 🔵 LOW | `app/infrastructure/db/postgres_user_repository.py:109` | `scalar_one()` trong `register_login_failure` raise `NoResultFound` nếu user bị xóa giữa chừng, thay vì xử lý gracefully |

---

## 2. `document-service`

### Điểm mạnh
- Soft-delete nhất quán (`deleted_at` filter khắp nơi)
- ACL normalization xử lý tốt nhiều format (comma-separated, JSON array, iterable)
- Audit logging đầy đủ (upload, delete, IP address)
- NATS subscriber dùng durable consumer + NAK on error đúng pattern
- DI/protocol separation clean

### Cần cải thiện

| Mức độ | File:Line | Vấn đề |
|--------|-----------|--------|
| 🔴 CRITICAL | `app/interfaces/api/dependencies.py:99` | `print()` raw JWT token ra stdout khi auth fail → **token bị leak vào log aggregator** (Datadog, CloudWatch...) — stolen log export = all tokens compromised |
| 🟠 HIGH | `app/application/use_cases/documents/common.py:54` | Admin không có bypass trong `can_access_document` → admin tự upload `top_secret` doc rồi không đọc được file của chính mình |
| 🟠 HIGH | `app/application/use_cases/documents/delete_document_use_case.py:63` | GCS delete **trước** DB soft-delete → nếu DB fail, file mất nhưng record vẫn tồn tại; mọi `get_document_file` sau đó trả GCS 404 |
| 🟠 HIGH | `app/application/use_cases/documents/upload_document_use_case.py:100` | GCS error không được wrap thành `StorageError` → trả 500 thay vì 503; client không phân biệt được service-down vs code bug |
| 🟡 MEDIUM | `app/infrastructure/messaging/nats_publisher.py:36` | Mỗi `publish()` mở + đóng **1 TCP connection mới** → tại 20 req/s = 40 NATS connections/giây, gây port exhaustion và cascade 503 |
| 🟡 MEDIUM | `app/interfaces/api/dependencies.py:93` | `jwt.decode` không enforce `verify_exp`, không chặn `algorithm=none` qua env var misconfiguration |
| 🟡 MEDIUM | `app/application/use_cases/documents/common.py:66` | `user.department == ""` (default) pass `secret` ACL nếu `allowed_departments` chứa empty string — ACL bypass tiềm ẩn |
| 🔵 LOW | `app/application/use_cases/documents/get_document_use_case.py:13` | `GET /documents/{id}` và `GET /documents` là admin-only → regular user không check được trạng thái document trước khi fetch file |

---

## 3. `query-service` + `mcp-service`

### Điểm mạnh
- Fail-closed contract verification ở startup (mcp-service exit code 1 nếu Qdrant index không match)
- ACL enforced **trước khi query Qdrant** — không bao giờ expose unauthorized doc cho search
- SSE connection scoped theo `user_id`, không cross-user leakage
- `_choose_tool` safe fallback về `rag_search` khi exception
- Tool decision whitelist validation tốt

### Cần cải thiện

| Mức độ | File:Line | Vấn đề |
|--------|-----------|--------|
| 🔴 CRITICAL | `app/infrastructure/config.py:14` | JWT secret mặc định `"your-secret-key-change-in-production"` — deploy production thiếu env var = attacker forge `role=admin` token |
| 🟠 HIGH | `app/infrastructure/config.py:56` | `enable_dev_endpoints` **default = `True`** → dev endpoint live trên production nếu không set `ENABLE_DEV_ENDPOINTS=false` |
| 🟠 HIGH | `app/interfaces/api/routers/notifications.py:60` | Pagination `limit` không có upper bound → `?limit=1000000` = full table scan, exhaust DB connections |
| 🟠 HIGH | `app/infrastructure/cache/rate_limiter.py` | `InMemoryRateLimiter` per-process → horizontal scale với 4 replicas = effective 4× rate limit; `redis_url` trong config không được dùng |
| 🟡 MEDIUM | `app/application/use_cases/query/orchestration.py:244` | Auto-summary **hardcode chuỗi tiếng Việt mock** sau 10 messages → overwrite conversation context thật bằng fake summary, corrupt multi-turn context |
| 🟡 MEDIUM | `app/infrastructure/messaging/notification_service.py:49` | NATS real event path vẫn notify **3 mock user hardcoded** thay vì real users → production users không nhận notification |
| 🟡 MEDIUM | `app/infrastructure/messaging/nats_events.py:43` | `_processed_event_ids` là unbounded in-memory set — không bao giờ evict, memory leak theo thời gian |
| 🔵 LOW | `mcp-service/app/core/vectorstore.py:161` | Qdrant client tạo mới **mỗi search request** → không có connection pooling, +20-50ms latency/request |

---

## 4. `rag-worker`

### Điểm mạnh
- Optimistic-lock job claiming (`SELECT` + conditional `UPDATE rowcount == 1`) — concurrent workers không double-claim
- Heartbeat + stale-reaper pattern để recover crashed worker — không cần manual intervention
- `BadPayloadError` (→ NATS `term`) vs transient error (→ NAK) — phân biệt đúng, tránh infinite retry
- S3 download có 5 lớp guard: HEAD size check, stream-to-disk, byte counter mid-stream, semaphore, `finally` cleanup
- Production fail-closed at startup (misconfigured AI provider / DB → hard raise)

### Cần cải thiện

| Mức độ | File:Line | Vấn đề |
|--------|-----------|--------|
| 🔴 CRITICAL | `app/infrastructure/db/postgres_document_repository.py:339` | Stale-job reaper **không có attempt cap** → job crash worker loop mãi mãi (PROCESSING → STALE → PROCESSING), không bao giờ reach FAILED terminal status |
| 🟠 HIGH | `app/application/use_cases/ingestion/ingest_document_use_case.py:195` | `delete()` không xóa `ingest_jobs` + `job_logs` → orphaned rows → re-ingest cùng `document_id` bị skip vì `find_active_job()` tìm thấy stale job |
| 🟠 HIGH | `app/application/use_cases/ingestion/ingest_document_use_case.py:59` | Dedup check `find_active_job()` **non-atomic** → 2 NATS delivery đồng thời = 2 PENDING jobs = double embedding cost + inconsistent vector sets (code tự comment TODO về missing unique partial index) |
| 🟠 HIGH | `app/interfaces/nats/ingest_consumer.py:89` | `document_name` không giới hạn độ dài so với DB `String(512)` → integrity error → NAK → **infinite retry storm** từ một poison message |
| 🟡 MEDIUM | `app/infrastructure/external/s3_parser.py:229` | `ContentLength=0` hoặc missing header bypass size guard → multi-GB object stream to disk trước khi mid-stream counter catch |
| 🟡 MEDIUM | `app/interfaces/api/routers/ingest.py:77` | `DELETE /ingest/{document_id}` **không có authentication** → bất kỳ caller nào reach được port này = xóa toàn bộ vectors + metadata |
| 🟡 MEDIUM | `app/infrastructure/db/postgres_document_repository.py:120` | `update_status(PROCESSING)` set `error_message = None` → xóa mất error history từ lần fail trước khi retry, phá post-mortem debugging |
| 🔵 LOW | `app/infrastructure/external/local_artifact_store.py:18` | `_artifact_path()` chỉ sanitize `/` và `\` trong `document_id` — các ký tự path-special khác (`..`, null bytes) không bị neutralize trên write path |

---

## Tổng kết & Priority Fixes

| Service | Điểm mạnh nổi bật | Vấn đề nghiêm trọng nhất |
|---------|-------------------|--------------------------|
| **user-service** | Auth security architecture solid | Missing `raise` = potential auth bypass; JWT TTL 8h |
| **document-service** | Soft-delete + audit log tốt | Token leak vào logs; GCS/DB operation order sai |
| **query-service** | ACL-before-query + fail-closed MCP | Mock summary hardcode; rate limiter per-process; dev endpoints default on |
| **rag-worker** | Job claiming + stale recovery pattern | Infinite retry loop; unauthenticated delete endpoint; non-atomic dedup |

### Fixes cần làm ngay trước production

1. **`user-service`** — Thêm `raise` tường minh sau `_handle_failed_password()`; validate JWT secret != default tại startup; giảm TTL xuống 15 phút
2. **`document-service`** — Xóa `print(token)` trong dependencies; đảo thứ tự DB soft-delete **trước** GCS delete
3. **`rag-worker`** — Thêm attempt cap (ví dụ `max_attempts=5`) vào stale-job reaper; thêm auth dependency cho `DELETE /ingest/{id}`
4. **`query-service`** — `enable_dev_endpoints` default → `False`; fix notification path dùng real users; thêm `Field(le=100)` cho pagination limit
