-- Trạng thái thực thi của action (vd đơn nghỉ phép) gắn vào message hội thoại.
-- Trước đây trạng thái "đã gửi" chỉ sống ở client (ActionableCard.isDone + localStorage)
-- -> reload/đổi thiết bị là mất, card hiện lại form như chưa gửi. Cột metadata cho phép
-- server là nguồn sự thật: keyed theo idempotency_key (đã tất định), lưu
--   {"actions": {"<idem>": {"status","request_id","leave_status","submitted_at"}}}
-- Xem docs/leave-action-state-b2.md.
ALTER TABLE query_svc.messages
    ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb;
