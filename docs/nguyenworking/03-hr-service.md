# HR Service — Tiến độ & việc cần làm

**Trạng thái:** 🟡 READ chạy (thiếu seed data); WRITE chưa code · **Mức hoàn thiện:** ~70% · **Cập nhật:** 2026-06-11
**Vai trò:** API nội bộ (internal only, KHÔNG route public qua nginx) — employee profile + 7 intent HR (READ). mcp-service gọi qua `HR_SERVICE_URL=http://hr-service:8004`.

> ⚠️ Đây là service **yếu nhất** trong 3 → ưu tiên dồn ở đây để cả luồng "HR cá nhân" vào production thật.

## Đã ổn định (căn bản XONG)
- ✅ **Endpoint `POST /hr/query`** với 7 intent READ (Clean Architecture: api / application / domain / infrastructure).
- ✅ **Self-access + audit** cho 3 intent nhạy cảm (payroll / benefits / performance) — `_audit()` log `SENSITIVE_INTENTS`, filter `WHERE user_id`.
- ✅ **Summary builder tiếng Việt** cho từng intent (đã fix khôi phục dấu tiếng Việt).
- ✅ **Migration Alembic** (`0001` / `0002`): bảng `leave_requests` / `leave_balance`, seed UUID làm contract e2e.
- ✅ **`hr_query.verify()` best-effort** + CI e2e Docker thật.

## Việc cần làm để vào Production thật

### 🔴 Cao
- [ ] **Seed HR data cho user demo** — admin demo (user `4f44e7f7f4c5`) KHÔNG có record → `hr_query` trả 404 → câu hỏi HR cá nhân ("số ngày phép còn lại của tôi") ra **NO_INFO**. Đây là việc #1 toàn cục. Cần script seed (xem `src/hr-service/scripts/`) + chạy migration trên VM.

### 🟡 Trung bình
- [ ] **Leave Request WRITE flow** (tạo/duyệt đơn nghỉ + NATS event) — 🟡 thiết kế đã chốt, **chưa code**. Ràng buộc:
  - Cần SA approve contract TRƯỚC khi merge.
  - Backward-compatible tuyệt đối, feature-flag OFF.
  - NATS best-effort (KHÔNG fail-closed).
  - KHÔNG đụng migration `0001` / `0002` → thêm migration mới.
  - Phối hợp với MCP tool WRITE `create_leave_request` ([02-mcp-service.md](02-mcp-service.md)).
- [ ] **Tăng coverage test** — hiện chỉ 1 file test (`tests/test_hr_query_endpoint.py`) so với rag-worker 36. Bổ sung test cho từng intent + audit path + self-access filter.

## Lưu ý vận hành / bẫy đã biết
- HR Service **internal only** — không expose public qua nginx; chỉ mcp-service gọi nội bộ qua `http://hr-service:8004` với header `X-Internal-Token`.
- 3 intent nhạy cảm (payroll/benefits/performance) bắt buộc self-access filter `WHERE user_id` + audit — đừng nới lỏng khi lên production.
- Env đến từ git (`deploy/env/*.env`); đổi cấu hình = sửa file env + commit + deploy.

## Liên kết
- Roadmap tổng: [00-roadmap.md](00-roadmap.md)
- Service docs: [../../src/hr-service/docs](../../src/hr-service/docs)
- Scripts seed: [../../src/hr-service/scripts](../../src/hr-service/scripts)
