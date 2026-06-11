# Definition of Done — Tiêu chí "Production thật"

**Cập nhật:** 2026-06-11

Một việc/feature chỉ được coi là **đã vào production thật** khi tick đủ checklist dưới. Dùng làm cổng kiểm trước khi đóng task trong [00-roadmap.md](00-roadmap.md).

## Checklist chung (mọi service)
- [ ] Code merge vào `develop` qua PR từ `nguyendev` (KHÔNG commit thẳng develop).
- [ ] CI xanh: unit + integration (e2e Docker) pass thật, không skip.
- [ ] Env cấu hình **đến từ git** (`deploy/env/*.env` commit thẳng) — không provision secret tay.
- [ ] Deploy `deploy-develop.yml` 3-phase chạy hết (test → Docker Hub `dadlks08` → VM pull).
- [ ] Smoke test deploy pass (nếu flake "khong nhan event done" → RE-RUN job trước khi đào code).
- [ ] **Verify trên VM thật** (`vsf-rag-demo-vm` 34.158.47.236, SSH qua gcloud IAP tunnel) — không chỉ tin CI.
- [ ] Quan sát được: log/trace ra đúng nơi (New Relic và/hoặc Langfuse), không bị nuốt.
- [ ] Backward-compatible; feature mới có feature-flag OFF mặc định.

## Tiêu chí riêng theo luồng

### Luồng RAG (RAG Worker + MCP `rag_search` + query)
- [ ] Ingest tài liệu thật → Qdrant `rag_chatbot__te3s__d1536` có chunk.
- [ ] Query "chính sách nghỉ phép hàng năm" trả `outcome=SUCCESS`, `sources≥1` với câu trả lời thật.
- [ ] Citation hiển thị nguồn đúng trên UI `https://vsfchat.cloud/chat`.

### Luồng HR cá nhân (HR Service + MCP `hr_query` + query)
- [ ] User demo có seed data trong `leave_balance` / `leave_requests`.
- [ ] Hỏi "số ngày phép còn lại của tôi" → ra số thật (KHÔNG NO_INFO/404).
- [ ] 3 intent nhạy cảm chỉ trả data của chính user (self-access filter) + có audit log.

## Định nghĩa "ổn định"
- Chạy liên tục ≥ vài ngày trên VM không crash loop.
- Tự recover sau lỗi hạ tầng thường gặp (mất kết nối Qdrant, collection biến mất) mà KHÔNG cần restart tay.
- Có đủ test bảo vệ regression cho các path chính.

## Liên kết
- Roadmap: [00-roadmap.md](00-roadmap.md)
- Per-service: [01-rag-worker.md](01-rag-worker.md) · [02-mcp-service.md](02-mcp-service.md) · [03-hr-service.md](03-hr-service.md)
