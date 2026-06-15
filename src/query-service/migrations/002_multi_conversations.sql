ALTER TABLE query_svc.conversations
    ADD COLUMN IF NOT EXISTS title text;

UPDATE query_svc.conversations AS conversation
SET title = COALESCE(
    NULLIF(BTRIM(conversation.title), ''),
    (
        SELECT LEFT(message.content, 48)
        FROM query_svc.messages AS message
        WHERE message.conversation_id = conversation.id
          AND message.role = 'user'
        ORDER BY message.created_at ASC
        LIMIT 1
    ),
    'Lịch sử trước đây'
)
WHERE conversation.title IS NULL
   OR BTRIM(conversation.title) = '';

ALTER TABLE query_svc.conversations
    ALTER COLUMN title SET DEFAULT 'Untitled chat',
    ALTER COLUMN title SET NOT NULL;

DO $$
DECLARE
    constraint_name text;
BEGIN
    FOR constraint_name IN
        SELECT con.conname
        FROM pg_constraint AS con
        JOIN pg_class AS rel ON rel.oid = con.conrelid
        JOIN pg_namespace AS nsp ON nsp.oid = rel.relnamespace
        WHERE nsp.nspname = 'query_svc'
          AND rel.relname = 'conversations'
          AND con.contype = 'u'
          AND pg_get_constraintdef(con.oid) = 'UNIQUE (user_id)'
    LOOP
        EXECUTE format(
            'ALTER TABLE query_svc.conversations DROP CONSTRAINT IF EXISTS %I',
            constraint_name
        );
    END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS idx_query_conversations_user_updated_at
    ON query_svc.conversations (user_id, updated_at DESC);
