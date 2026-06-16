-- Bảng user_access_profile bị thiếu migration (chỉ có trong data-schema.md, chưa từng
-- tạo trên DB). Hệ quả sự cố 2026-06-16: hr.employee_profile.updated -> upsert_profile
-- INSERT vào bảng không tồn tại -> nats_event_processing_failed -> NAK redeliver vô tận
-- (flood log + đập DB) -> query-service nghẽn -> RAG 0 sources -> DEPLOY FAIL.
-- Đồng thời department theo HR không propagate -> ACL non-admin (sếp/nhân viên) mất quyền.
CREATE TABLE IF NOT EXISTS query_svc.user_access_profile (
    user_id           uuid PRIMARY KEY,
    account_type      varchar(20) NOT NULL,        -- internal | external
    department        varchar(100),
    employment_status varchar(20) NOT NULL,         -- active | inactive | terminated | contractor
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_access_department
    ON query_svc.user_access_profile (department);

CREATE INDEX IF NOT EXISTS idx_user_access_account_type
    ON query_svc.user_access_profile (account_type);
