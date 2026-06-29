# CÒN TỒN ĐỌNG — 3 service (RAG / MCP / HR) + đồng bộ danh tính

**Cập nhật:** 2026-06-17 · Người phụ trách: Nguyen Tran · Branch: `nguyendev` → PR `develop` → deploy VM

> File này GOM toàn bộ việc **chưa xong**. Cách thi công từng việc xem [CACH-XU-LY.md](CACH-XU-LY.md) (đánh số khớp: T1…T8).
> Phạm vi quyền: RAG Worker, MCP Service, HR Service + được phép đụng `query-service` (để 3 service chạy thông với agent LangGraph). Service khác (frontend/user/document) ngoài phạm vi trừ khi cần phối hợp.

## Trạng thái tổng quan

| Service | Runtime | % | Khoảng cách tới Production thật |
|---------|---------|---|--------------------------------|
| **RAG Worker** | 🟢 Production, verified E2E + Langfuse | ~97% | Polish chất lượng chunk/caption (log stdout JSON đã xong T3) |
| **MCP Service** | 🟢 Production, WRITE tool đã merge | ~93% | Network hardening (fail-closed auth + middleware token đã xong T6); còn internal-only routing |
| **HR Service** | 🟢 READ + WRITE (leave request) đã merge | ~90% | Verify sync trên VM (T1); log JSON + test coverage + WRITE flow đã xong |

"Production thật" = chạy ổn định trên VM `vsf-rag-demo-vm` (35.240.193.13), phục vụ `https://vsfchat.cloud`, đủ tin cậy + quan sát được (New Relic/Langfuse) + xử lý dữ liệu thật, không chỉ demo.

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
- ✅ **T4 ĐÃ CODE & MERGE** (`4f7351a`, `839f2ce` — 2026-06-16): Leave Request WRITE flow đầy đủ.
  - **HR:** `leave_write_repository.py` + `postgres_hr_repository` impl WRITE (migration mới, không đụng `0001`/`0002`); validate qua `leave_balance`; chống trùng đơn (chặn trùng toàn bộ + cảnh báo chồng ngày — `839f2ce`); publish NATS best-effort. Tests: `test_leave_write_endpoint/repo_postgres/resilience.py` + `test_leave_policy.py`.
  - **MCP:** tool WRITE `leave_write.py` + 2 tool mới `leave_approvals.py` (duyệt đơn), `leave_types.py` (loại nghỉ) — proxy sang hr với `X-Internal-Token`; dynamic MCP tools. Test `test_leave_write_tool.py`.
  - Doc impl: `src/hr-service/docs/leave-request-write-implementation.md`.
- ✅ **T6 middleware token ĐÃ XONG** (cùng đợt leave-write): `src/hr-service/app/api/auth.py` enforce `X-Internal-Token` phía hr; mọi MCP tool gắn token khi gọi hr. → còn lại CHỈ network internal-only routing.

---

## Bảng việc còn lại (impact × độ chặn)

🔴 chặn trải nghiệm thật · 🟡 quan trọng có workaround · 🟢 polish

| # | Việc | Service | Ưu tiên | Trạng thái | Chặn gì |
|---|------|---------|---------|------------|---------|
| **T1** | Verify đồng bộ user→hr→query **trên VM** (code đã merge; CD đã tự gác) | HR/User/Query | 🔴 | ◑ Đã thêm guard CD, chờ deploy chạy xanh + mắt thấy 1 lần | Sai → câu HR cá nhân vẫn NO_INFO; ACL phòng ban rỗng/sai |
| **T2** | Tuning TRIAGE bớt CLARIFY với câu policy đã rõ | query | 🔴 | ✅ XONG (`3e2ee5a`) — chờ verify CI/VM | — |
| **T3** | Fix structured log INFO không ra docker stdout | RAG/all | 🟡 | ✅ XONG (`3e2ee5a`) — hr JSON stdout | — |
| **T4** | Code Leave Request WRITE flow (HR + MCP `leave_write`/`leave_approvals`/`leave_types`) | HR + MCP | 🟡 | ✅ XONG (`4f7351a`, `839f2ce`) — tạo/duyệt đơn + chống trùng | — |
| **T5** | Tăng coverage test hr-service (hiện ~2 file) | HR | 🟡 | ✅ XONG (`3e2ee5a`) — 26/26 pass | — |
| **T6** | MCP security hardening | MCP | 🟡 | ◑ Phần lớn — fail-closed auth (`3e2ee5a`) + middleware enforce `X-Internal-Token` (`auth.py`) XONG; còn network internal-only | Network: hr-service không route public |
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

### T4 — Leave Request WRITE flow (HR + MCP) ✅ XONG (`4f7351a`, `839f2ce`)
Đã code & merge đầy đủ (06-16):
- **HR:** `leave_write_repository.py` + impl trong `postgres_hr_repository.py` (migration mới, KHÔNG đụng `0001`/`0002`); use case validate qua `leave_balance`; **chống trùng đơn** (chặn trùng toàn bộ, cảnh báo chồng ngày — `839f2ce`); publish NATS best-effort.
- **MCP:** `leave_write.py` (tạo đơn) + `leave_approvals.py` (duyệt) + `leave_types.py` (loại nghỉ) — proxy hr với `X-Internal-Token`, dynamic tool registration; KHÔNG ảnh hưởng `rag_search`/`hr_query`.
- **Test:** `test_leave_write_endpoint/repo_postgres/resilience.py`, `test_leave_policy.py` (hr) + `test_leave_write_tool.py` (mcp).
- Doc: `src/hr-service/docs/leave-request-write-implementation.md`.
**Còn lại:** verify trên VM với flag ON + đối soát NATS event đơn nghỉ thực tế.

### T5 — Coverage test hr-service ✅ XONG (`3e2ee5a`)
Thêm `test_hr_intents_coverage.py` (+167): leave/attendance/onboarding happy+NO_INFO, audit path 3 intent nhạy cảm (payroll/benefits/performance, mask user_id), self-access filter, Unicode tiếng Việt. Local hr-service 26/26 pass.

### T6 — MCP security hardening ◑ PHẦN LỚN (`3e2ee5a` + đợt leave-write)
✅ **Fail-closed auth** đã xong: `enforce_production_auth()` — `app_env=production` mà thiếu `MCP_INTERNAL_TOKEN` → raise (chặn deploy fail-open), gọi trong `main` trước `build_mcp`. Test 6/6 pass.
✅ **Middleware enforce token** đã xong: `src/hr-service/app/api/auth.py` reject caller thiếu/sai `X-Internal-Token` ở app layer phía hr; mọi MCP tool (`hr_query`, `leave_write`, `leave_approvals`, `leave_types`) gắn token khi proxy.
**Còn lại:** network hardening (hr-service internal-only, không route public); rà giới hạn tool theo enabled policy khi prod. Xem `src/mcp-service/docs/security-hardening.md`.

### T7 — Env vào GitHub secret 🟡
rag/mcp/hr đã theo env-từ-git; đồng bộ nốt user/document/query (set qua PyNaCl API). Env phải trỏ Qdrant nội bộ `qdrant:6333` (KHÔNG cloud → 404 crash).

### T8 — Chất lượng chunk/caption (gap6–gap9) 🟢
Polish độ chính xác retrieval. KHÔNG chặn production. Docs gap: `src/rag-worker/docs/gap`.

---

## Bug ghi nhận

### B1 — Agent tự mặc định `annual` (phép năm) khi user không nêu loại nghỉ 🟡 (chưa fix)
**Ghi nhận:** 2026-06-18. Phát hiện trên `https://vsfchat.cloud/chat`.
**Tái hiện:** user nhắn *"cho tôi nghỉ phép thứ 2 tuần sau nhé"* (không nêu loại/lý do) → agent dựng draft đơn **Phép năm** (`leave_type=annual`), không hỏi lại.
**Nguyên nhân (by-design, không phải lỗi code):** prompt `TRIAGE/LEAVE CONFIRMATION` ở `src/query-service/app/application/prompts.py:260-266` ép map "việc riêng thường ngày / nghỉ chung chung" → `annual` và dòng 266 *"Default to annual when the user just wants time off without a special reason."* Từ "phép" trong "nghỉ phép" càng đẩy về phép năm.
**Rủi ro:** tự trừ **quỹ phép năm** khi user chưa chọn loại nghỉ. Giảm nhẹ một phần: UI confirmation form có dropdown cho sửa loại nghỉ trước khi "Xác nhận & Gửi".
**Quyết định cần chốt (chưa code):** khi loại nghỉ **mơ hồ** thì giữ default `annual` (hiện tại) hay **hỏi lại 1 câu** ("Bạn muốn nghỉ phép năm hay loại khác?"). Nếu chọn hỏi lại → sửa ở prompt (không đụng retrieval/tool), thêm test routing.

### B2 — Thiếu validate ngày quá khứ + range ở tầng server (chỉ `resolve_date` chặn) 🔴 (đã xác minh, chưa fix)
**Ghi nhận:** 2026-06-18. **Đã xác minh code.**
**Tái hiện:** xin nghỉ vào ngày **đã qua** (vd `30/04/2026` khi hôm nay 18/06/2026) vẫn tạo được đơn nếu đi đường vòng qua guard.
**Phân tích (defence-in-depth thủng — chốt chặn chỉ ở 1 tầng model-invoked):**
- ✅ Chốt DUY NHẤT: `src/mcp-service/app/tools/resolve_date.py:115-129` — ngày `< hôm nay` → `past_date:True` + gợi ý năm sau.
- ❌ Đường vòng 1 — prompt `src/query-service/app/application/prompts.py:270-271` cho phép **skip `resolve_date`** khi user gõ thẳng `YYYY-MM-DD` → ngày tuyệt đối không qua guard.
- ❌ Đường vòng 2 — `src/hr-service/app/infrastructure/db/postgres_hr_repository.py:789` `create_leave_request` KHÔNG check `start < today`, **cũng không check `end < start`** (dòng 766/883 `days_count=(end-start).days+1` có thể **âm**). Interface `leave_write_repository.py` không có exception ngày quá khứ / range không hợp lệ.
- ❌ Đường vòng 3 — UI confirmation form có date-picker sửa tay → chọn về ngày quá khứ, không gì chặn.
**Hướng fix (chưa code):** thêm validate **authoritative ở hr-service** (`create_leave_request` + `update_leave_request`): reject `start_date < today` (giờ VN) và `end_date < start_date` → exception mới (vd `LeaveRequestInvalidDate`) → routes map 422. + test fail-trước-pass-sau (ngày quá khứ / end<start). Đây mới là chốt thật; `resolve_date` chỉ là UX layer.

---

## Lộ trình gợi ý
- ~~**Đợt A:** T1 → T2 → T3~~ → T2/T3 XONG (`3e2ee5a`); còn **T1 (verify VM)** sau khi deploy `develop`.
- **Đợt B (tin cậy + an toàn):** ~~T5~~ ~~T6 middleware~~ XONG → T6 network internal-only → T7 (env secret).
- ~~**Đợt C (mở rộng WRITE):** T4~~ → T4 XONG (`4f7351a`/`839f2ce`); còn verify VM với flag ON.
- **Polish:** T8 khi rảnh.

### Còn lại sau leave-write (`4f7351a`/`839f2ce`) (ưu tiên giảm dần)
1. 🔴 **T1** — deploy `develop` → chạy `user-backfill`, mắt thấy admin hỏi HR ra số phép thật trên VM (CD đã tự gác smoke 5c).
2. 🟡 **T4 (verify)** — flag ON staging → tạo/duyệt đơn chạy thật + đối soát NATS event đơn nghỉ.
3. 🟡 **T6 (phần còn)** — network internal-only (hr không route public).
4. 🟡 **T7** — env user/document/query → GitHub secret (đồng bộ convention).
5. 🟢 **T8** — chunk/caption tuning (gap6–gap9).

## Definition of Done (cổng kiểm trước khi đóng task)
**Chung mọi service:** PR `nguyendev`→`develop` (không commit thẳng) · CI unit + e2e Docker xanh thật (không skip) · env đến từ git (`deploy/env/*.env`) · deploy 3-phase chạy hết · smoke pass (flake "khong nhan event done" → RE-RUN trước khi đào code) · **verify trên VM thật** · log/trace ra đúng nơi · backward-compatible + flag OFF mặc định.

**Luồng RAG:** ingest doc thật → Qdrant có chunk; query "chính sách nghỉ phép hàng năm" → `outcome=SUCCESS`, `sources≥1`; citation đúng trên `https://vsfchat.cloud/chat`.

**Luồng HR cá nhân:** user demo có data; hỏi "số ngày phép còn lại của tôi" → ra số thật (không NO_INFO/404); 3 intent nhạy cảm chỉ trả data của chính user + có audit log.

**"Ổn định":** chạy ≥ vài ngày không crash loop; tự recover sau lỗi hạ tầng (mất Qdrant, collection biến mất) mà KHÔNG cần restart tay; đủ test chống regression.
</content>
