# Roadmap — Đưa 3 service vào Production thật

**Cập nhật:** 2026-06-12 · Người phụ trách: Nguyen Tran

## 1. Trạng thái tổng quan

| Service | Trạng thái runtime | Mức hoàn thiện | Khoảng cách tới Production thật |
|---------|--------------------|----------------|--------------------------------|
| **RAG Worker** | 🟢 Production, verified E2E + Langfuse | ~96% | Chỉ còn tuning chất lượng chunk/caption (polish). Hardening reliability XONG. |
| **MCP Service** | 🟢 Production, verified `CallToolRequest` | ~85% | Tool WRITE + security hardening |
| **HR Service** | 🟡 READ chạy, thiếu seed data; WRITE chưa code | ~70% | Seed data + WRITE flow + test coverage |

> "Production thật" ở đây = chạy ổn định trên VM `vsf-rag-demo-vm`, phục vụ `https://vsfchat.cloud`, có đủ độ tin cậy + quan sát được + xử lý được dữ liệu thật của khách, không chỉ demo. Tiêu chí chi tiết: [04-definition-of-done.md](04-definition-of-done.md).

## 2. Bảng ưu tiên toàn cục

Sắp theo **impact × độ chặn**. 🔴 = chặn trải nghiệm thật / 🟡 = quan trọng nhưng có workaround / 🟢 = polish.

| # | Việc | Service | Ưu tiên | Trạng thái | Ghi chú |
|---|------|---------|---------|------------|---------|
| 1 | **Seed HR data cho user demo** (fix NO_INFO câu hỏi HR cá nhân) | HR | 🔴 | ☐ Chưa | Admin demo `4f44e7f7f4c5` không có record → `hr_query` 404 |
| 2 | **Tuning prompt trả lời + retrieval** (chống cắt ngắn, tổng hợp đủ chunk) | query | 🔴 | ◑ Một phần | ✅ Answer-prompt + retrieval XONG (`1b517ba`, deploy develop 06-12): bỏ "ngắn gọn→cắt", tổng hợp TẤT CẢ chunk, cho trả lời một phần; `rag_top_k=8`, trần `top_k`→10, `rag_score_threshold=0.35`. ☐ Còn lại: tuning TRIAGE bớt CLARIFY với câu policy rõ |
| 3 | **Fix structured log INFO không ra docker stdout** | RAG/all | 🟡 | ☐ Chưa | Hạ từ 🔴: Langfuse tracing (deploy 06-11) đã cho kênh quan sát thay thế; vẫn nên fix log thường ngày |
| 4 | ~~Hardening Qdrant `_ensure`/recreate reliability~~ | RAG | ✅ | **XONG** | self-heal collection-missing (409a38a) + classify→transient + 4 test. Gap `gap-qdrant-ensure-recreate` RESOLVED. |
| 5 | **Code Leave Request WRITE flow** (sau khi SA approve contract) | HR + MCP | 🟡 | ☐ Chưa | feature-flag OFF, backward-compatible, NATS best-effort |
| 6 | **Tăng coverage test hr-service** | HR | 🟡 | ☐ Chưa | Hiện chỉ 1 file test |
| 7 | **MCP security hardening** | MCP | 🟡 | ☐ Chưa | `docs/security-hardening.md` |
| 8 | **Đưa env user/document/query vào GitHub secret** (đồng bộ rag/mcp/hr) | Infra | 🟡 | ☐ Chưa | |
| 9 | Tuning chất lượng chunk/caption (gap6–gap9) | RAG | 🟢 | ☐ Chưa | Polish chất lượng retrieval |

## 3. Lộ trình theo đợt (sprint gợi ý)

### Đợt A — "Production thật cho luồng RAG + HR cá nhân" (ưu tiên ngay)
Mục tiêu: người dùng hỏi cả câu policy (RAG) lẫn câu HR cá nhân ("số ngày phép còn lại") đều ra câu trả lời đúng, và đội vận hành quan sát được hệ thống.
- [ ] #1 Seed HR data
- [◑] #2 Answer-prompt + retrieval XONG (06-12); còn tuning TRIAGE bớt CLARIFY
- [ ] #3 Fix log INFO ra stdout

### Đợt B — "Độ tin cậy + an toàn"
- [ ] #4 Qdrant `_ensure` hardening
- [ ] #6 Test coverage hr-service
- [ ] #7 MCP security hardening
- [ ] #8 Env vào GitHub secret

### Đợt C — "Mở rộng tính năng WRITE"
- [ ] #5 Leave Request WRITE flow (HR + MCP) — cần SA approve contract trước

## 4. Nguyên tắc khi đưa lên production
- Mọi thay đổi env đến **TỪ GIT** (`deploy/env/*.env` commit thẳng) — không provision secret tay (xem convention env).
- Env phải trỏ Qdrant nội bộ `qdrant:6333`, KHÔNG trỏ cloud (cloud → 404 crash).
- Mọi remote Qdrant client qua `VectorStoreConfig.remote_client_kwargs()` (port 443 + timeout).
- Deploy `git reset --hard` trên VM → KHÔNG sửa tay trên VM, mọi sửa qua git.
- Feature mới: feature-flag OFF mặc định, backward-compatible tuyệt đối.
- Smoke test deploy hay flake "khong nhan event done" → RE-RUN job trước khi đào code.

## 5. Liên kết
- Chi tiết per-service: [01-rag-worker.md](01-rag-worker.md) · [02-mcp-service.md](02-mcp-service.md) · [03-hr-service.md](03-hr-service.md)
- Báo cáo gốc 06-10: [../BAO_CAO_TIEN_DO_rag-mcp-hr.md](../BAO_CAO_TIEN_DO_rag-mcp-hr.md)
