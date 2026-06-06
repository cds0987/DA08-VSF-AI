CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS query_svc;

CREATE TABLE IF NOT EXISTS query_svc.conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL UNIQUE,
    summary text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS query_svc.messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES query_svc.conversations(id) ON DELETE CASCADE,
    user_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content text NOT NULL,
    session_id text,
    sources jsonb NOT NULL DEFAULT '[]'::jsonb,
    latency_ms integer,
    feedback integer CHECK (feedback IN (-1, 1)),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_query_messages_conversation_created_at
    ON query_svc.messages (conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_query_messages_session_id
    ON query_svc.messages (session_id)
    WHERE session_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS query_svc.document_access (
    document_id uuid PRIMARY KEY,
    classification text NOT NULL,
    allowed_departments text[] NOT NULL DEFAULT ARRAY[]::text[],
    allowed_user_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS query_svc.notifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    event text NOT NULL,
    message text NOT NULL,
    doc_id uuid,
    is_read boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_query_notifications_user_created_at
    ON query_svc.notifications (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_query_notifications_unread
    ON query_svc.notifications (user_id, is_read)
    WHERE is_read = false;
