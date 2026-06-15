# Data Schema — RAG Chatbot

Mỗi service kết nối đến **database riêng** trên cùng 1 GCP Cloud SQL db-g1-small: `user_db`, `doc_db`, `query_db`, `mcp_db`, `hr_db`, `langfuse_db`.

> **Convention chung:**
> - `id`: `UUID PRIMARY KEY DEFAULT gen_random_uuid()`
> - Timestamps: `TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()`
> - Soft delete: `deleted_at TIMESTAMP WITH TIME ZONE NULL`

---

## Migration Strategy

Schema được quản lý bằng **Alembic** — mỗi service có thư mục `alembic/` riêng.

- Thêm column mới → tạo migration mới, không sửa DDL trực tiếp
- `alembic upgrade head` — áp migration mới nhất
- `alembic downgrade -1` — rollback 1 bước nếu cần

> File DDL trong doc này là **tham chiếu** — source of truth là các file migration trong repo.

---

## User Service — Schema `user_svc`

```sql
CREATE TABLE user_svc.users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               VARCHAR(255) UNIQUE NOT NULL,
    hashed_password     VARCHAR(255),                                -- NULL nếu đăng nhập qua Microsoft SSO
    auth_provider       VARCHAR(20) NOT NULL DEFAULT 'local',        -- 'local' | 'microsoft'
    role                VARCHAR(20) NOT NULL DEFAULT 'user',         -- 'admin' | 'user'
    account_type        VARCHAR(20) NOT NULL DEFAULT 'internal',     -- 'internal' | 'external'
    is_active           BOOLEAN NOT NULL DEFAULT true,
    department          VARCHAR(100) NOT NULL DEFAULT '',            -- Phase 1 snapshot. Source of truth production: hr_db.hr_svc.employees.department
    failed_login_count  INTEGER NOT NULL DEFAULT 0,
    locked_until        TIMESTAMP WITH TIME ZONE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX idx_users_email ON user_svc.users(email);
CREATE INDEX idx_users_account_type ON user_svc.users(account_type);

CREATE TABLE user_svc.refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES user_svc.users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(255) NOT NULL,                      -- bcrypt hash của raw refresh token
    expires_at  TIMESTAMP WITH TIME ZONE NOT NULL,          -- now() + 7 days
    revoked_at  TIMESTAMP WITH TIME ZONE,                   -- set khi logout hoặc rotate
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX idx_refresh_tokens_user ON user_svc.refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_hash ON user_svc.refresh_tokens(token_hash);

-- Per-service audit: các hành động auth + quản lý user (User Service tự ghi).
CREATE TABLE user_svc.audit_logs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id      UUID NOT NULL,
    actor_role    VARCHAR(50) NOT NULL,
    action        VARCHAR(100) NOT NULL,     -- 'login'|'logout'|'login_failed'|'password_change'|'account_locked'|'grant_admin'|'revoke_admin'|'deactivate'|'reactivate'
    resource_type VARCHAR(100),             -- 'user'
    resource_id   UUID,
    detail        JSONB,
    ip_address    VARCHAR(45),
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX idx_user_audit_actor ON user_svc.audit_logs(actor_id, created_at DESC);
```

---

## Query Service — Database `query_db`

```sql
CREATE TABLE query_svc.conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL,
    summary     TEXT,                                            -- LLM-generated summary của các turns cũ (Summary Buffer)
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE query_svc.messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES query_svc.conversations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL,
    role            VARCHAR(20) NOT NULL,        -- 'user' | 'assistant'
    content         TEXT NOT NULL,
    sources         JSONB,                       -- assistant only: [{document_id, document_name, caption, heading_path, score, source_gcs_uri}]
    latency_ms      INTEGER,
    feedback        SMALLINT,                    -- 1 | -1 | NULL
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_user_created ON query_svc.messages(user_id, created_at DESC);

-- Projection ACL (event-driven, database-per-service).
-- Bản sao quyền truy cập tài liệu, do doc_access_subscriber cập nhật từ event NATS `doc.access`
-- (Document Service publish). Query Service đọc bảng này cho ACL pre-filter — KHÔNG đọc thẳng doc_db.
CREATE TABLE query_svc.document_access (
    document_id         UUID PRIMARY KEY,                            -- = doc_id bên doc_db
    classification      VARCHAR(20) NOT NULL,                        -- public|internal|secret|top_secret
    allowed_departments TEXT[] NOT NULL DEFAULT '{}',
    allowed_user_ids    TEXT[] NOT NULL DEFAULT '{}',
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()  -- thời điểm event gần nhất
);

CREATE INDEX idx_doc_access_classification ON query_svc.document_access(classification);

-- Projection hồ sơ truy cập user, cập nhật từ HR Service qua event NATS
-- `hr.employee_profile.updated` (WRITE/propagation path — KHÔNG phải read hr_query).
-- Query Service dùng bảng này để lọc tài liệu theo account_type/department/
-- employment_status mà không gọi trực tiếp HR Service trên hot path chat.
-- ⏳ Nguồn publish hiện là scaffold (NatsPublisher stub ở hr-service, chưa wire) —
--    bảng tồn tại nhưng chưa nhận event thật cho tới khi nhánh NATS được implement.
CREATE TABLE query_svc.user_access_profile (
    user_id           UUID PRIMARY KEY,
    account_type      VARCHAR(20) NOT NULL,       -- internal | external
    department        VARCHAR(100),
    employment_status VARCHAR(20) NOT NULL,       -- active | inactive | terminated | contractor
    updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX idx_user_access_department ON query_svc.user_access_profile(department);
CREATE INDEX idx_user_access_account_type ON query_svc.user_access_profile(account_type);

-- Notification Center: lưu thông báo để xem lại + đếm chưa đọc (badge).
-- notify_subscriber ghi 1 bản ghi/user khi đẩy event SSE; FE đọc qua GET /notifications/history.
CREATE TABLE query_svc.notifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL,
    event       VARCHAR(50) NOT NULL,        -- 'doc_new' | ...
    message     TEXT NOT NULL,
    doc_id      UUID,
    is_read     BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX idx_notifications_user ON query_svc.notifications(user_id, created_at DESC);
CREATE INDEX idx_notifications_unread ON query_svc.notifications(user_id) WHERE is_read = false;
```

> Đây là **read-model** (eventual consistency): khi Admin đổi quyền ở Document Service → event `doc.access`
> → bảng này cập nhật sau vài giây. Document Service chết không ảnh hưởng — Query Service vẫn đọc bản sao local.
> Xóa tài liệu: event `doc.access { deleted:true }` → xóa bản ghi tương ứng.

---

## Document Service — Database `doc_db`

> RAG Worker có metadata DB riêng (`rag_db`) cho ingest job/document state. Document Service vẫn là owner của document catalog trong `doc_db`; Qdrant + GCS giữ vector/artifact.

```sql
CREATE TABLE doc_svc.documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                VARCHAR(500) NOT NULL,
    file_type           VARCHAR(20) NOT NULL,                        -- pdf | docx | txt | xlsx | csv | pptx | md
    gcs_key             VARCHAR(1000) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'queued',       -- DocumentStatus: queued|processing|indexed|failed (Admin upload → queued thẳng, không có approve/reject)
    uploaded_by         UUID NOT NULL,                               -- user_id từ User Service
    classification      VARCHAR(20) NOT NULL DEFAULT 'internal',     -- public|internal|secret|top_secret
    allowed_departments TEXT[] NOT NULL DEFAULT '{}',
    allowed_user_ids    TEXT[] NOT NULL DEFAULT '{}',
    chunk_count         INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_documents_status ON doc_svc.documents(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_documents_uploader ON doc_svc.documents(uploaded_by) WHERE deleted_at IS NULL;

-- Per-service audit: chỉ các hành động liên quan tài liệu (Document Service tự ghi).
CREATE TABLE doc_svc.audit_logs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id      UUID NOT NULL,
    actor_role    VARCHAR(50) NOT NULL,
    action        VARCHAR(100) NOT NULL,     -- 'upload'|'delete'|'reindex'
    resource_type VARCHAR(100),             -- 'document'
    resource_id   UUID,
    detail        JSONB,
    ip_address    VARCHAR(45),
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_actor ON doc_svc.audit_logs(actor_id, created_at DESC);
```

---

## HR Service — Database `hr_db`, Schema `hr_svc`

> HR Service sở hữu employee profile, department và mock HR data cho Feature 5b (Personal HR Q&A). Tool **`hr_query`** của **mcp-service** gọi HR Service bằng internal HTTP/gRPC; Query Service không đụng trực tiếp DB này. Filter bắt buộc `WHERE user_id = :current_user_id` (user_id do MCP client inject từ JWT). `external` accounts không có HR personal data.

```sql
CREATE TABLE hr_svc.departments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code        VARCHAR(50) UNIQUE NOT NULL,
    name        VARCHAR(255) NOT NULL,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE hr_svc.employees (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID UNIQUE NOT NULL,       -- logical reference to user_db.user_svc.users.id
    employee_code     VARCHAR(50) UNIQUE,
    company_email     VARCHAR(255) UNIQUE NOT NULL,
    department        VARCHAR(100) NOT NULL,
    job_title         VARCHAR(150),
    manager_user_id   UUID,                      -- logical reference to direct manager's user_id
    employment_status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX idx_employees_user ON hr_svc.employees(user_id);
CREATE INDEX idx_employees_department ON hr_svc.employees(department);
CREATE INDEX idx_employees_manager ON hr_svc.employees(manager_user_id);

CREATE TABLE hr_svc.leave_balance (
    user_id             UUID PRIMARY KEY,
    annual_leave_total  INTEGER NOT NULL DEFAULT 12,
    annual_leave_used   INTEGER NOT NULL DEFAULT 0,
    sick_leave_total    INTEGER NOT NULL DEFAULT 10,
    sick_leave_used     INTEGER NOT NULL DEFAULT 0,
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE hr_svc.leave_requests (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL,
    employee_id          UUID REFERENCES hr_svc.employees(id),
    leave_type           VARCHAR(20) NOT NULL,    -- 'annual' | 'sick' | 'personal'
    start_date           DATE NOT NULL,
    end_date             DATE NOT NULL,
    days_count           INTEGER NOT NULL,
    status               VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending|approved|rejected|cancelled
    reason               TEXT,
    approver_user_id     UUID NOT NULL,           -- MVP: sếp trực tiếp = employees.manager_user_id
    approved_at          TIMESTAMP WITH TIME ZONE,
    rejected_at          TIMESTAMP WITH TIME ZONE,
    rejected_reason      TEXT,
    created_at           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX idx_leave_req_user ON hr_svc.leave_requests(user_id);
CREATE INDEX idx_leave_req_status ON hr_svc.leave_requests(status);
CREATE INDEX idx_leave_req_approver ON hr_svc.leave_requests(approver_user_id, status);

-- Chấm công theo kỳ 'YYYY-MM' — self-access (intent attendance)
CREATE TABLE hr_svc.attendance (
    user_id     UUID PRIMARY KEY,
    period      VARCHAR(7) NOT NULL,        -- 'YYYY-MM'
    work_days   INTEGER NOT NULL DEFAULT 0,
    late_count  INTEGER NOT NULL DEFAULT 0,
    absent_count INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Onboarding checklist — self-access (intent onboarding), item linh hoạt dạng JSONB
CREATE TABLE hr_svc.onboarding (
    user_id     UUID PRIMARY KEY,
    status      VARCHAR(20) NOT NULL DEFAULT 'in_progress',
    checklist   JSONB NOT NULL DEFAULT '[]',     -- [{"task": ..., "done": bool}]
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE hr_svc.payroll_summary (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL,
    period       VARCHAR(7) NOT NULL,        -- 'YYYY-MM' vd: '2026-05'
    gross_salary NUMERIC(12, 2) NOT NULL,
    deductions   NUMERIC(12, 2) NOT NULL DEFAULT 0,
    net_salary   NUMERIC(12, 2) NOT NULL,
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    UNIQUE(user_id, period)
);

CREATE INDEX idx_payroll_user ON hr_svc.payroll_summary(user_id, period DESC);

-- Phúc lợi (benefits) — self-access, item linh hoạt dạng JSONB
CREATE TABLE hr_svc.benefits (
    user_id    UUID PRIMARY KEY,
    items      JSONB NOT NULL DEFAULT '[]',     -- [{"name": ..., "value": ...}]
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Đánh giá hiệu suất (performance) — self-access, theo kỳ 'YYYY-MM'
CREATE TABLE hr_svc.performance_reviews (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL,
    period           VARCHAR(7) NOT NULL,        -- 'YYYY-MM'
    rating           VARCHAR(20) NOT NULL,
    kpi              JSONB NOT NULL DEFAULT '[]',
    reviewer_user_id UUID,                        -- ai đánh giá (nullable)
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    UNIQUE(user_id, period)
);

CREATE INDEX idx_performance_user ON hr_svc.performance_reviews(user_id, period DESC);
```

> **Intent đã expose qua `hr_query`:** `leave_balance`, `leave_requests`, `attendance`, `onboarding`, **`payroll`**, **`benefits`**, **`performance`**.
> **Mô hình truy cập = self-access:** mọi query lọc cứng `WHERE user_id = <token user>`. Intent nhạy cảm (`payroll`/`benefits`/`performance`) **không cần role-gate** vì là data của chính user; hr-service ghi **audit log** mỗi lần truy cập (không log số liệu). Mở rộng manager-xem-cấp-dưới (dùng `employees.manager_user_id`) để dành cho giai đoạn sau — additive, không phá contract hiện tại.
> `recruitment` **hoãn** — vốn là dữ liệu cross-user (ứng viên), không hợp mô hình self-access.
> `employee_profile` / `org_structure` **không tạo bảng** — lấy từ JWT claim (user-service sở hữu data đó).
> Migration: `0001_create_hr_schema` (7 bảng đầu) + `0002_add_benefits_performance` (benefits, performance_reviews).

---

## Qdrant Collection — Vector Payload

Collection name: `rag_chatbot`

```json
{
  "chunk_id": "uuid",
  "chunk_type": "child",
  "parent_id": "uuid",
  "parent_text": "string",
  "child_text": "string",
  "document_id": "uuid",
  "document_name": "string",
  "file_type": "pdf | docx | txt | xlsx | csv | pptx | md",
  "page_number": 1,
  "section_title": "string",
  "heading_path": ["Chính sách công tác", "Hoàn tiền vé máy bay"],
  "source_uri": "gs://bucket/raw/{doc_id}/file.pdf",
  "artifact_uri": "gs://bucket/artifacts/{doc_id}/markdown.md",
  "classification": "public | internal | secret | top_secret",
  "allowed_departments": ["HR", "Finance"],
  "allowed_user_ids": ["uuid"],
  "uploaded_by": "uuid",
  "ocr_confidence": 0.95
}
```

> Vector dimension: 1536 (text-embedding-3-small). Chỉ embed `child_text`. `parent_text` lưu trong payload để đưa vào LLM context. `source_uri` trỏ tới file gốc; `artifact_uri` trỏ tới canonical Markdown artifact do rag-worker ghi sau parse/OCR. Production path của artifact là `gs://<bucket>/artifacts/{document_id}/markdown.md`; không dùng `/tmp/artifacts` làm storage bền. mcp-service đọc payload trực tiếp từ Qdrant để dựng `SearchHit` (KHÔNG qua NATS, KHÔNG cần tra DB) và map `source_uri` → `source_gcs_uri`, `artifact_uri` → `markdown_gcs_uri` ở response tool. `section_title` → map sang `caption`, `heading_path` (breadcrumb) → map thẳng sang SearchResult. `ocr_confidence` chỉ có với PDF scan, dùng để flag low-quality chunks. Chunk size: Parent-Child (LlamaIndex HierarchicalNodeParser) — config TBD sau khi implement.

---

## Redis — Key Patterns

| Key | Value | TTL | Mục đích |
|-----|-------|-----|---------|
| `blacklist:{jti}` | `"1"` | Còn lại của token (tối đa 8h) | JWT revocation — logout thật sự |
| `rate_limit:{user_id}:{minute}` | request count | 60 giây | Throttle per-user, ví dụ max 20 req/phút |
| `semantic_cache:{query_hash}` | JSON response | 1 giờ | Cache RAG response cho câu hỏi tương tự |

> `jti` = JWT ID — field unique trong mỗi token, thêm vào payload khi phát hành.
