# CÒN TỒN ĐỌNG — 3 service (RAG / MCP / HR) + đồng bộ danh tính

**Cập nhật:** 2026-06-12 · Người phụ trách: Nguyen Tran · Branch: `nguyendev` → PR `develop` → deploy VM

> File này GOM toàn bộ việc **chưa xong**. Cách thi công từng việc xem [CACH-XU-LY.md](CACH-XU-LY.md) (đánh số khớp: T1…T8).
> Phạm vi quyền: RAG Worker, MCP Service, HR Service + được phép đụng `query-service` (để 3 service chạy thông với agent LangGraph). Service khác (frontend/user/document) ngoài phạm vi trừ khi cần phối hợp.

## Trạng thái tổng quan

| Service | Runtime | % | Khoảng cách tới Production thật |
|---------|---------|---|--------------------------------|
| **RAG Worker** | 🟢 Production, verified E2E + Langfuse | ~96% | Polish chất lượng chunk/caption + fix log stdout |
| **MCP Service** | 🟢 Production, verified `CallToolRequest` | ~85% | Tool WRITE + security hardening |
| **HR Service** | 🟡 READ chạy; WRITE chưa code | ~70% | Verify sync trên VM + WRITE flow + test coverage |

"Production thật" = chạy ổn định trên VM `vsf-rag-demo-vm` (34.158.47.236), phục vụ `https://vsfchat.cloud`, đủ tin cậy + quan sát được (New Relic/Langfuse) + xử lý dữ liệu thật, không chỉ demo.

### Đã XONG (không lặp ở dưới — ghi để khỏi làm lại)
- ✅ Cả 4 service (rag/hr/document/user) dùng **Alembic**, baseline idempotent (`7d7c6e3` — hết cần `stamp` tay), mỗi service có `*-migrate` one-shot trong compose.
- ✅ Đồng bộ danh tính đã **CODE & MERGE** (`5799eca`, `083ffc2`, `25d500d`): `user-backfill` one-shot trong `docker-compose.yml` + `.e2e.yml`; hr `NatsPublisher` **impl thật** (publish `hr.employee_profile.updated` qua JetStream `HR_EVENTS`); hr subscriber `user.*` + lazy auto-create `leave_balance`; hạn mức phép ra config. → còn lại CHỈ là verify VM (T1).
- ✅ RAG Worker: pipeline ingest đầy đủ (OCR→chunk→caption→embed→Qdrant `rag_chatbot__te3s__d1536`); Langfuse tracing ingest (deploy 06-11); Qdrant `_ensure` self-heal collection-missing (`409a38a`) — hết phải restart tay.
- ✅ query-service: answer-prompt + retrieval tuning (`1b517ba`, deploy 06-12): bỏ "ngắn gọn→cắt", tổng hợp tất cả chunk, `rag_top_k=8` (trần 10), `rag_score_threshold=0.35`.

---

## Bảng việc còn lại (impact × độ chặn)

🔴 chặn trải nghiệm thật · 🟡 quan trọng có workaround · 🟢 polish

| # | Việc | Service | Ưu tiên | Trạng thái | Chặn gì |
|---|------|---------|---------|------------|---------|
| **T1** | Verify đồng bộ user→hr→query **trên VM** (code đã merge; CD đã tự gác) | HR/User/Query | 🔴 | ◑ Đã thêm guard CD, chờ deploy chạy xanh + mắt thấy 1 lần | Sai → câu HR cá nhân vẫn NO_INFO; ACL phòng ban rỗng/sai |
| **T2** | Tuning TRIAGE bớt CLARIFY với câu policy đã rõ | query | 🔴 | ◑ Một phần (retrieval xong) | Bot hỏi lại thừa khi câu đã đủ rõ |
| **T3** | Fix structured log INFO không ra docker stdout | RAG/all | 🟡 | ☐ Chưa | Log thường ngày bị nuốt (Langfuse thay tạm) |
| **T4** | Code Leave Request WRITE flow (HR + MCP `create_leave_request`) | HR + MCP | 🟡 | ☐ Chưa (thiết kế xong) | Chưa cho tạo/duyệt đơn nghỉ; cần SA approve contract |
| **T5** | Tăng coverage test hr-service (hiện ~2 file) | HR | 🟡 | ☐ Chưa | Regression dễ lọt |
| **T6** | MCP security hardening | MCP | 🟡 | ☐ Chưa | Auth MCP↔hr + giới hạn tool khi prod |
| **T7** | Đưa env user/document/query vào GitHub secret | Infra | 🟡 | ☐ Chưa | Lệch convention env-từ-git |
| **T8** | Tuning chất lượng chunk/caption (gap6–gap9) | RAG | 🟢 | ☐ Chưa | Độ chính xác retrieval (không chặn prod) |

---

## Chi tiết từng việc

### T1 — Verify đồng bộ danh tính trên VM 🔴 (KHÔNG code nghiệp vụ mới)
✅ **Đã thêm guard tự động vào CD** (`deploy-develop.yml` bước `5c` SMOKE luồng-vàng HR): sau deploy hỏi THẲNG hr-service `leave_balance` cho user vừa login → bắt buộc 200 + `annual_remaining` là số, nếu 404/NO_INFO → fail deploy + rollback. Vá điểm pass-giả cũ (smoke LLM `need=0` cho NO_INFO lọt). → mỗi deploy tự gác sync user→hr.
Còn lại = quan sát 1 lần cho chắc:
- Deploy `develop` lên VM, chạy `user-backfill` → log "đã phát user.created cho N user".
- Hỏi HR cho admin thật (`4f44e7f7…`, `admin@company.com`) "số ngày phép còn lại của tôi" → ra **số thật**, KHÔNG NO_INFO/404.
- Tạo/đổi user → `query_svc.user_access_profile` có/đổi row tương ứng (chiều hr→query, cập nhật ACL phòng ban).
- Xác nhận hr **không loop** (subscriber chỉ nghe `user.*`, KHÔNG nghe `hr.employee_profile.updated`).

### T2 — Tuning TRIAGE bớt CLARIFY 🔴
Answer-prompt + retrieval đã xong. **Còn lại:** node TRIAGE còn trả CLARIFY với câu policy đã rõ → nới ngưỡng quyết định, giữ CLARIFY chỉ cho câu thực sự mơ hồ.

### T3 — Log INFO ra docker stdout 🟡
Root logger ở WARNING → log INFO bị nuốt. Đã giảm nhẹ nhờ Langfuse (debug qua trace) nên hạ 🔴→🟡, nhưng vẫn cần fix để có log thường ngày rẻ.

### T4 — Leave Request WRITE flow (HR + MCP) 🟡
Thiết kế đã chốt, **chưa code**. Ràng buộc cứng: **SA approve contract TRƯỚC**; feature-flag OFF mặc định; backward-compatible tuyệt đối; NATS best-effort (KHÔNG fail-closed); KHÔNG đụng migration `0001`/`0002` → thêm migration mới.

### T5 — Coverage test hr-service 🟡
Hiện ~2 file test (rag-worker 36+). Bổ sung test từng intent + audit path + self-access filter (3 intent nhạy cảm: payroll/benefits/performance).

### T6 — MCP security hardening 🟡
Rà auth MCP ↔ hr-service (`X-Internal-Token`), giới hạn tool theo enabled policy khi prod. hr-service internal-only, KHÔNG route public.

### T7 — Env vào GitHub secret 🟡
rag/mcp/hr đã theo env-từ-git; đồng bộ nốt user/document/query (set qua PyNaCl API). Env phải trỏ Qdrant nội bộ `qdrant:6333` (KHÔNG cloud → 404 crash).

### T8 — Chất lượng chunk/caption (gap6–gap9) 🟢
Polish độ chính xác retrieval. KHÔNG chặn production. Docs gap: `src/rag-worker/docs/gap`.

---

## Lộ trình gợi ý
- **Đợt A (ngay):** T1 (verify VM) → T2 (TRIAGE) → T3 (log).
- **Đợt B (tin cậy + an toàn):** T5 (test hr) → T6 (MCP security) → T7 (env secret).
- **Đợt C (mở rộng WRITE):** T4 — cần SA approve contract trước.
- **Polish:** T8 khi rảnh.

## Definition of Done (cổng kiểm trước khi đóng task)
**Chung mọi service:** PR `nguyendev`→`develop` (không commit thẳng) · CI unit + e2e Docker xanh thật (không skip) · env đến từ git (`deploy/env/*.env`) · deploy 3-phase chạy hết · smoke pass (flake "khong nhan event done" → RE-RUN trước khi đào code) · **verify trên VM thật** · log/trace ra đúng nơi · backward-compatible + flag OFF mặc định.

**Luồng RAG:** ingest doc thật → Qdrant có chunk; query "chính sách nghỉ phép hàng năm" → `outcome=SUCCESS`, `sources≥1`; citation đúng trên `https://vsfchat.cloud/chat`.

**Luồng HR cá nhân:** user demo có data; hỏi "số ngày phép còn lại của tôi" → ra số thật (không NO_INFO/404); 3 intent nhạy cảm chỉ trả data của chính user + có audit log.

**"Ổn định":** chạy ≥ vài ngày không crash loop; tự recover sau lỗi hạ tầng (mất Qdrant, collection biến mất) mà KHÔNG cần restart tay; đủ test chống regression.
</content>
