# CÒN TỒN ĐỌNG — 3 service (RAG / MCP / HR) + đồng bộ danh tính

**Cập nhật:** 2026-06-13 · Người phụ trách: Nguyen Tran · Branch: `nguyendev` → PR `develop` → deploy VM

> File này GOM toàn bộ việc **chưa xong**. Cách thi công từng việc xem [CACH-XU-LY.md](CACH-XU-LY.md) (đánh số khớp: T1…T8).
> Phạm vi quyền: RAG Worker, MCP Service, HR Service + được phép đụng `query-service` (để 3 service chạy thông với agent LangGraph). Service khác (frontend/user/document) ngoài phạm vi trừ khi cần phối hợp.

## Trạng thái tổng quan

| Service | Runtime | % | Khoảng cách tới Production thật |
|---------|---------|---|--------------------------------|
| **RAG Worker** | 🟢 Production, verified E2E + Langfuse | ~97% | Polish chất lượng chunk/caption (log stdout JSON đã xong T3) |
| **MCP Service** | 🟢 Production, verified `CallToolRequest` | ~88% | Tool WRITE (T4) + network hardening (fail-closed auth đã xong T6) |
| **HR Service** | 🟡 READ chạy; WRITE chưa code | ~80% | Verify sync trên VM (T1) + WRITE flow (T4); log JSON + test coverage đã xong |

"Production thật" = chạy ổn định trên VM `vsf-rag-demo-vm` (34.158.47.236), phục vụ `https://vsfchat.cloud`, đủ tin cậy + quan sát được (New Relic/Langfuse) + xử lý dữ liệu thật, không chỉ demo.

### Đã XONG (không lặp ở dưới — ghi để khỏi làm lại)
- ✅ Cả 4 service (rag/hr/document/user) dùng **Alembic**, baseline idempotent (`7d7c6e3` — hết cần `stamp` tay), mỗi service có `*-migrate` one-shot trong compose.
- ✅ Đồng bộ danh tính đã **CODE & MERGE** (`5799eca`, `083ffc2`, `25d500d`): `user-backfill` one-shot trong `docker-compose.yml` + `.e2e.yml`; hr `NatsPublisher` **impl thật** (publish `hr.employee_profile.updated` qua JetStream `HR_EVENTS`); hr subscriber `user.*` + lazy auto-create `leave_balance`; hạn mức phép ra config. → còn lại CHỈ là verify VM (T1).
- ✅ RAG Worker: pipeline ingest đầy đủ (OCR→chunk→caption→embed→Qdrant `rag_chatbot__te3s__d1536`); Langfuse tracing ingest (deploy 06-11); Qdrant `_ensure` self-heal collection-missing (`409a38a`) — hết phải restart tay.
- ✅ query-service: answer-prompt + retrieval tuning (`1b517ba`, deploy 06-12): bỏ "ngắn gọn→cắt", tổng hợp tất cả chunk, `rag_top_k=8` (trần 10), `rag_score_threshold=0.35`.
- ✅ **T2/T3/T5/T6 ĐÃ CODE & MERGE** (`3e2ee5a`, 2026-06-13) — chờ CI xanh + verify VM:
  - **T2** (query): nới TRIAGE — thêm policy/domain keyword anchor (nghỉ phép, lương, chính sách) → câu policy rõ KHÔNG rơi CLARIFY; CLARIFY chỉ last-resort. + `test_triage.py` khoá hợp đồng routing (fake model).
  - **T3** (hr): `configure_logging` JSON ra stdout (idempotent), đồng nhất rag-worker. + `test_logging_utils.py`.
  - **T5** (hr): `test_hr_intents_coverage.py` (+167) — leave/attendance/onboarding happy+NO_INFO, audit path 3 intent nhạy cảm (mask user_id), self-access, Unicode TV. Local hr-service 26/26 pass.
  - **T6** (mcp): `enforce_production_auth()` fail-closed — `app_env=production` mà thiếu `MCP_INTERNAL_TOKEN` → raise (chặn deploy fail-open). + test 6/6 pass.

---

## Bảng việc còn lại (impact × độ chặn)

🔴 chặn trải nghiệm thật · 🟡 quan trọng có workaround · 🟢 polish

| # | Việc | Service | Ưu tiên | Trạng thái | Chặn gì |
|---|------|---------|---------|------------|---------|
| **T1** | Verify đồng bộ user→hr→query **trên VM** (code đã merge; CD đã tự gác) | HR/User/Query | 🔴 | ◑ Đã thêm guard CD, chờ deploy chạy xanh + mắt thấy 1 lần | Sai → câu HR cá nhân vẫn NO_INFO; ACL phòng ban rỗng/sai |
| **T2** | Tuning TRIAGE bớt CLARIFY với câu policy đã rõ | query | 🔴 | ✅ XONG (`3e2ee5a`) — chờ verify CI/VM | — |
| **T3** | Fix structured log INFO không ra docker stdout | RAG/all | 🟡 | ✅ XONG (`3e2ee5a`) — hr JSON stdout | — |
| **T4** | Code Leave Request WRITE flow (HR + MCP `create_leave_request`) | HR + MCP | 🟡 | ☐ Chưa (thiết kế xong) | Chưa cho tạo/duyệt đơn nghỉ; cần SA approve contract |
| **T5** | Tăng coverage test hr-service (hiện ~2 file) | HR | 🟡 | ✅ XONG (`3e2ee5a`) — 26/26 pass | — |
| **T6** | MCP security hardening | MCP | 🟡 | ◑ Một phần — fail-closed auth XONG (`3e2ee5a`); còn middleware enforce + network | Auth MCP↔hr + giới hạn tool khi prod |
| **T7** | Đưa env user/document/query vào GitHub secret | Infra | 🟡 | ☐ Chưa | Lệch convention env-từ-git |
| **T8** | Tuning chất lượng chunk/caption (gap6–gap9) | RAG | 🟢 | ☐ Chưa | Độ chính xác retrieval (không chặn prod) |

---

## Chi tiết từng việc

### Stage develop — mock data cho mọi user (2026-06-13, mới thêm)
Thêm biến **`APP_STAGE`** (develop|production) theo branch (env-từ-git: develop branch commit `develop`, main branch commit `production`). Khi `APP_STAGE=develop`, hr-service tự sinh **mock data idempotent** (deterministic theo user_id) cho mọi intent READ (`attendance/onboarding/payroll/benefits/performance/leave_requests`) khi user đồng bộ chưa có hồ sơ → test end-to-end với tài khoản thật KHÔNG còn NO_INFO. Production giữ 404. `provision_mock` là method concrete (không vỡ ABC); `leave_balance` vẫn dùng `ensure_leave_balance` cũ. Test: hr-service 40/40 pass.
⚠️ Pipeline hiện chỉ deploy từ `develop`; muốn production thật (data thật, không mock) phải tách deploy sang branch `main` với `APP_STAGE=production`. WRITE flow (tạo/duyệt đơn) vẫn là T4.

### T1 — Verify đồng bộ danh tính trên VM 🔴 (KHÔNG code nghiệp vụ mới)
✅ **Đã thêm guard tự động vào CD** (`deploy-develop.yml` bước `5c` SMOKE luồng-vàng HR): sau deploy hỏi THẲNG hr-service `leave_balance` cho user vừa login → bắt buộc 200 + `annual_remaining` là số, nếu 404/NO_INFO → fail deploy + rollback. Vá điểm pass-giả cũ (smoke LLM `need=0` cho NO_INFO lọt). → mỗi deploy tự gác sync user→hr.
Còn lại = quan sát 1 lần cho chắc:
- Deploy `develop` lên VM, chạy `user-backfill` → log "đã phát user.created cho N user".
- Hỏi HR cho admin thật (`4f44e7f7…`, `admin@company.com`) "số ngày phép còn lại của tôi" → ra **số thật**, KHÔNG NO_INFO/404.
- Tạo/đổi user → `query_svc.user_access_profile` có/đổi row tương ứng (chiều hr→query, cập nhật ACL phòng ban).
- Xác nhận hr **không loop** (subscriber chỉ nghe `user.*`, KHÔNG nghe `hr.employee_profile.updated`).

### T2 — Tuning TRIAGE bớt CLARIFY ✅ XONG (`3e2ee5a`)
Đã nới `TRIAGE_SYSTEM_PROMPT` (prompts.py): thêm policy/domain keyword anchor (nghỉ phép, lương, chính sách…) → câu policy rõ KHÔNG rơi CLARIFY; CLARIFY chỉ còn last-resort khi không có anchor. Thêm `test_triage.py` khoá hợp đồng routing (fake model). **Còn lại:** verify trên CI (test cần langgraph) + mắt thấy trên VM giảm false CLARIFY thực tế.

### T3 — Log INFO ra docker stdout ✅ XONG (`3e2ee5a`)
hr-service đã thay `logging.basicConfig` (text) bằng `configure_logging` JSON ra stdout (idempotent), đồng nhất với rag-worker. Thêm `test_logging_utils.py`. → log thường ngày ra đúng nơi, không còn phụ thuộc Langfuse để debug.

### T4 — Leave Request WRITE flow (HR + MCP) 🟡
Thiết kế đã chốt, **chưa code**. Ràng buộc cứng: **SA approve contract TRƯỚC**; feature-flag OFF mặc định; backward-compatible tuyệt đối; NATS best-effort (KHÔNG fail-closed); KHÔNG đụng migration `0001`/`0002` → thêm migration mới.

### T5 — Coverage test hr-service ✅ XONG (`3e2ee5a`)
Thêm `test_hr_intents_coverage.py` (+167): leave/attendance/onboarding happy+NO_INFO, audit path 3 intent nhạy cảm (payroll/benefits/performance, mask user_id), self-access filter, Unicode tiếng Việt. Local hr-service 26/26 pass.

### T6 — MCP security hardening ◑ MỘT PHẦN (`3e2ee5a`)
✅ **Fail-closed auth** đã xong: `enforce_production_auth()` — `app_env=production` mà thiếu `MCP_INTERNAL_TOKEN` → raise (chặn deploy fail-open), gọi trong `main` trước `build_mcp`. Test 6/6 pass.
**Còn lại:** middleware auth enforce reject caller (`X-Internal-Token`) ở app layer; network hardening (internal-only, không route public); giới hạn tool theo enabled policy khi prod. Xem `src/mcp-service/docs/security-hardening.md`.

### T7 — Env vào GitHub secret 🟡
rag/mcp/hr đã theo env-từ-git; đồng bộ nốt user/document/query (set qua PyNaCl API). Env phải trỏ Qdrant nội bộ `qdrant:6333` (KHÔNG cloud → 404 crash).

### T8 — Chất lượng chunk/caption (gap6–gap9) 🟢
Polish độ chính xác retrieval. KHÔNG chặn production. Docs gap: `src/rag-worker/docs/gap`.

---

## Lộ trình gợi ý
- ~~**Đợt A:** T1 → T2 → T3~~ → T2/T3 XONG (`3e2ee5a`); còn **T1 (verify VM)** sau khi deploy `develop`.
- **Đợt B (tin cậy + an toàn):** ~~T5~~ XONG → T6 phần còn lại (middleware + network) → T7 (env secret).
- **Đợt C (mở rộng WRITE):** T4 — cần SA approve contract trước.
- **Polish:** T8 khi rảnh.

### Còn lại sau `3e2ee5a` (ưu tiên giảm dần)
1. 🔴 **T1** — deploy `develop` → chạy `user-backfill`, mắt thấy admin hỏi HR ra số phép thật trên VM (CD đã tự gác smoke 5c).
2. 🟡 **T6 (phần còn)** — middleware enforce `X-Internal-Token` + network internal-only.
3. 🟡 **T7** — env user/document/query → GitHub secret (đồng bộ convention).
4. 🟡 **T4** — Leave Request WRITE flow (cần SA approve contract trước).
5. 🟢 **T8** — chunk/caption tuning (gap6–gap9).

## Definition of Done (cổng kiểm trước khi đóng task)
**Chung mọi service:** PR `nguyendev`→`develop` (không commit thẳng) · CI unit + e2e Docker xanh thật (không skip) · env đến từ git (`deploy/env/*.env`) · deploy 3-phase chạy hết · smoke pass (flake "khong nhan event done" → RE-RUN trước khi đào code) · **verify trên VM thật** · log/trace ra đúng nơi · backward-compatible + flag OFF mặc định.

**Luồng RAG:** ingest doc thật → Qdrant có chunk; query "chính sách nghỉ phép hàng năm" → `outcome=SUCCESS`, `sources≥1`; citation đúng trên `https://vsfchat.cloud/chat`.

**Luồng HR cá nhân:** user demo có data; hỏi "số ngày phép còn lại của tôi" → ra số thật (không NO_INFO/404); 3 intent nhạy cảm chỉ trả data của chính user + có audit log.

**"Ổn định":** chạy ≥ vài ngày không crash loop; tự recover sau lỗi hạ tầng (mất Qdrant, collection biến mất) mà KHÔNG cần restart tay; đủ test chống regression.
</content>
