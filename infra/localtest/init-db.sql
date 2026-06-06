-- LOCAL TEST DB bootstrap (postgres container, chạy 1 lần khi volume rỗng).
-- Tạo các DB + schema/bảng cho document-service (rag_db để alembic của rag-worker lo).

CREATE DATABASE doc_db;
CREATE DATABASE rag_db;

\connect doc_db

CREATE SCHEMA IF NOT EXISTS doc_svc;

CREATE TABLE IF NOT EXISTS doc_svc.documents (
    id                  UUID PRIMARY KEY,
    name                VARCHAR(500) NOT NULL,
    file_type           VARCHAR(20)  NOT NULL,
    gcs_key             VARCHAR(1000) NOT NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'queued',
    uploaded_by         UUID         NOT NULL,
    classification      VARCHAR(20)  NOT NULL DEFAULT 'internal',
    allowed_departments TEXT[]       NOT NULL DEFAULT '{}',
    allowed_user_ids    TEXT[]       NOT NULL DEFAULT '{}',
    chunk_count         INTEGER      NOT NULL DEFAULT 0,
    error_message       TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_doc_status ON doc_svc.documents (status);
CREATE INDEX IF NOT EXISTS ix_doc_uploaded_by ON doc_svc.documents (uploaded_by);

CREATE TABLE IF NOT EXISTS doc_svc.audit_logs (
    id            UUID PRIMARY KEY,
    actor_id      UUID         NOT NULL,
    actor_role    VARCHAR(50)  NOT NULL,
    action        VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100),
    resource_id   UUID,
    detail        JSONB,
    ip_address    VARCHAR(45),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_audit_actor ON doc_svc.audit_logs (actor_id);
