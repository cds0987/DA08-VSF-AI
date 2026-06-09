CREATE SCHEMA IF NOT EXISTS user_svc;

ALTER TABLE user_svc.users
    ADD COLUMN IF NOT EXISTS account_type VARCHAR(20) NOT NULL DEFAULT 'internal';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_users_account_type'
    ) THEN
        ALTER TABLE user_svc.users
            ADD CONSTRAINT ck_users_account_type
            CHECK (account_type IN ('internal', 'external'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_users_account_type
    ON user_svc.users(account_type);
