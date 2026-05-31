# Data Schema — RAG Chatbot

Mỗi service dùng PostgreSQL schema riêng trên cùng 1 RDS instance, tách bằng `CREATE SCHEMA`.

> **Convention chung:**
> - `id`: `UUID PRIMARY KEY DEFAULT gen_random_uuid()`
> - Timestamps: `TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()`
> - Soft delete: `deleted_at TIMESTAMP WITH TIME ZONE NULL`

---

## User Service — Schema `user_svc`

```sql
CREATE TABLE user_svc.users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               VARCHAR(255) UNIQUE NOT NULL,
    hashed_password     VARCHAR(255),                                -- NULL nếu đăng nhập qua Microsoft SSO
    auth_provider       VARCHAR(20) NOT NULL DEFAULT 'local',        -- 'local' | 'microsoft'
    role                VARCHAR(20) NOT NULL DEFAULT 'user',         -- 'admin' | 'user'
    is_active           BOOLEAN NOT NULL DEFAULT true,
    department          VARCHAR(100) NOT NULL DEFAULT '',            -- dùng cho Secret filter Phase 2
    failed_login_count  INTEGER NOT NULL DEFAULT 0,
    locked_until        TIMESTAMP WITH TIME ZONE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX idx_users_email ON user_svc.users(email);
```

---

## Chat Service — Schema `chat_svc`

```sql
CREATE TABLE chat_svc.conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL,
    summary     TEXT,                                            -- LLM-generated summary của các turns cũ (Summary Buffer)
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE chat_svc.messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES chat_svc.conversations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL,
    role            VARCHAR(20) NOT NULL,        -- 'user' | 'assistant'
    content         TEXT NOT NULL,
    sources         JSONB,                       -- [{document_name, page_number, score, chunk_text}]
    latency_ms      INTEGER,
    feedback        SMALLINT,                    -- 1 | -1 | NULL
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_user_created ON chat_svc.messages(user_id, created_at DESC);
```

---

## RAG Service — Schema `rag_svc`

```sql
CREATE TABLE rag_svc.documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                VARCHAR(500) NOT NULL,
    file_type           VARCHAR(20) NOT NULL,                        -- pdf | docx | txt | xlsx | csv | pptx | md
    s3_key              VARCHAR(1000) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',      -- DocumentStatus enum
    uploaded_by         UUID NOT NULL,                               -- user_id từ User Service
    classification      VARCHAR(20) NOT NULL DEFAULT 'internal',     -- public|internal|secret|top_secret
    allowed_departments TEXT[] NOT NULL DEFAULT '{}',
    allowed_user_ids    TEXT[] NOT NULL DEFAULT '{}',
    chunk_count         INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    rejection_reason    TEXT,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_documents_status ON rag_svc.documents(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_documents_uploader ON rag_svc.documents(uploaded_by) WHERE deleted_at IS NULL;

CREATE TABLE rag_svc.audit_logs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id      UUID NOT NULL,
    actor_role    VARCHAR(50) NOT NULL,
    action        VARCHAR(100) NOT NULL,     -- 'upload'|'approve'|'reject'|'delete'|'login'|'login_failed'
    resource_type VARCHAR(100),             -- 'document'|'user'
    resource_id   UUID,
    detail        JSONB,
    ip_address    VARCHAR(45),
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_actor ON rag_svc.audit_logs(actor_id, created_at DESC);
```

---

## HR Mock Data — Schema `hr_mock` (trong RAG Service DB)

> Mock data cho Feature 5b (Personal HR Q&A). Filter bắt buộc `WHERE user_id = :current_user_id`.

```sql
CREATE TABLE hr_mock.leave_balance (
    user_id             UUID PRIMARY KEY,
    annual_leave_total  INTEGER NOT NULL DEFAULT 12,
    annual_leave_used   INTEGER NOT NULL DEFAULT 0,
    sick_leave_total    INTEGER NOT NULL DEFAULT 10,
    sick_leave_used     INTEGER NOT NULL DEFAULT 0,
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE hr_mock.leave_requests (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL,
    leave_type  VARCHAR(20) NOT NULL,    -- 'annual' | 'sick' | 'personal'
    start_date  DATE NOT NULL,
    end_date    DATE NOT NULL,
    days_count  INTEGER NOT NULL,
    status      VARCHAR(20) NOT NULL,   -- 'pending' | 'approved' | 'rejected'
    reason      TEXT,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX idx_leave_req_user ON hr_mock.leave_requests(user_id);

CREATE TABLE hr_mock.payroll_summary (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL,
    period       VARCHAR(7) NOT NULL,        -- 'YYYY-MM' vd: '2026-05'
    gross_salary NUMERIC(12, 2) NOT NULL,
    deductions   NUMERIC(12, 2) NOT NULL DEFAULT 0,
    net_salary   NUMERIC(12, 2) NOT NULL,
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    UNIQUE(user_id, period)
);

CREATE INDEX idx_payroll_user ON hr_mock.payroll_summary(user_id, period DESC);
```

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
  "classification": "public | internal | secret | top_secret",
  "allowed_departments": ["HR", "Finance"],
  "allowed_user_ids": ["uuid"],
  "uploaded_by": "uuid",
  "ocr_confidence": 0.95
}
```

> Vector dimension: 1024 (BGE-M3). Chỉ embed `child_text`. `parent_text` lưu trong payload để đưa vào LLM context. `ocr_confidence` chỉ có với PDF scan, dùng để flag low-quality chunks. Chunk size: Child 128–256 token, Parent 512–1024 token, overlap 20–30 token.

---

## Redis — Key Patterns

| Key | Value | TTL | Mục đích |
|-----|-------|-----|---------|
| `blacklist:{jti}` | `"1"` | Còn lại của token (tối đa 8h) | JWT revocation — logout thật sự |
| `rate_limit:{user_id}:{minute}` | request count | 60 giây | Throttle per-user, ví dụ max 20 req/phút |
| `semantic_cache:{query_hash}` | JSON response | 1 giờ | Cache RAG response cho câu hỏi tương tự _(Phase 2)_ |

> `jti` = JWT ID — field unique trong mỗi token, thêm vào payload khi phát hành.
