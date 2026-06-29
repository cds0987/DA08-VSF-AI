# CÁCH XỬ LÝ — Hướng dẫn thi công cho coder

**Cập nhật:** 2026-06-12 · Đối tượng: dev rag-worker / mcp-service / hr-service / query-service

> Đánh số khớp [TON-DONG.md](TON-DONG.md) (T1…T8). Mỗi mục: **làm ở đâu · làm gì · test · done khi**.

---

## PHẦN A — Nền tảng (đọc 1 lần, áp dụng mọi task)

### A.1 Quy tắc vàng (vi phạm = trả lại PR)
1. Branch từ `nguyendev`, mỗi task 1 PR → `develop`. KHÔNG commit thẳng `develop`/`main`.
2. **Clean Architecture, đúng layer:** `domain` không import ai (không boto3/httpx/qdrant/sqlalchemy); `application` (use_cases) chỉ phụ thuộc `domain` qua interface/Protocol; `infrastructure`/`interfaces` ở ngoài cùng, wire ở `composition`. **Đừng nhét logic vào router/consumer.**
3. Thêm key `config.yaml` → thêm field `config_schema.py` **cùng commit** (nếu không CI parity fail `extra_forbidden`).
4. Env = sửa `deploy/env/*.env` + commit. KHÔNG provision secret tay, KHÔNG sửa tay trên VM (deploy `git reset --hard` xóa).
5. Feature mới = **feature-flag OFF mặc định** + backward-compatible tuyệt đối.
6. Async: `asyncio_mode=auto` → viết `async def test_...` thẳng, không cần `@pytest.mark.asyncio`.
7. CI xanh ≠ chạy được → luồng E2E phải **verify trên VM thật**.

### A.2 Viết test chặt (test pyramid)
- **Unit** (nhiều nhất): 1 use_case/1 hàm domain, **Stub thủ công** port (ghi lại call để assert) — KHÔNG lạm dụng `unittest.mock.Mock`.
- **Integration:** adapter chạm hạ tầng giả (Qdrant in-mem/offline embedder, sqlite/fixture).
- **E2E** (`tests/e2e`, Docker): vài kịch bản xương sống.
- **Eval** (`tests/eval`): chất lượng retrieval/answer.

Mỗi feature phải có test: **happy · edge** (rỗng/null/top_k=0/Unicode tiếng Việt giữ dấu) **· failure** (adapter ném lỗi → xử lý đúng) **· fallback/best-effort · idempotency** (ingest/consumer) **· self-access** (hr nhạy cảm). Test fail-fast: **KHÔNG NATS thật, KHÔNG sleep**, deterministic; test fail-trước-pass-sau (bug → viết regression tái hiện trước).

```powershell
# trong thư mục service (vd src/rag-worker)
python -m pytest                                  # tất cả
python -m pytest tests/application                # 1 layer
python -m pytest -k ingest -q                     # lọc tên
python -m pytest tests/.../test_x.py::test_case   # 1 case
```

### A.3 Bẫy đã biết (đọc để khỏi vỡ)
| Bẫy | Hậu quả | Cách tránh |
|-----|---------|-----------|
| Thêm key `config.yaml` quên `config_schema.py` | CI parity `extra_forbidden` | Sửa 2 file cùng commit |
| Remote Qdrant không qua `remote_client_kwargs()` | Cloud Run ConnectTimeout | Luôn qua `VectorStoreConfig.remote_client_kwargs()` (port 443 + timeout) |
| Env trỏ Qdrant cloud thay vì `qdrant:6333` | 404 crash khi deploy | Env trỏ Qdrant **nội bộ** |
| Xóa nguyên collection Qdrant | ingest 404 (cache `_ready`) | ĐÃ self-heal (`409a38a`); vẫn restart nếu nghi cache lệch khác |
| Sửa tay trên VM | deploy `git reset --hard` ghi đè | Mọi sửa qua git |
| mcp dùng chung `core_engine` rag-worker | phá tính độc lập | mcp tự dựng hạ tầng, ghép **chỉ qua Qdrant URL** |
| Mất dấu tiếng Việt trong summary | output sai | Test có case Unicode tiếng Việt |
| pybreaker `call_async` (tornado) trong asyncio | NameError, gãy MCP | Dùng `_AsyncCircuitBreaker` asyncio-native |
| Tin CI smoke pass = ổn | smoke chỉ check 2xx | Verify luồng thật trên VM |
| Smoke flake "khong nhan event done" | tưởng vỡ code | RE-RUN job deploy TRƯỚC khi đào code |

### A.4 Quy tắc đồng bộ event (cho T1/T4)
- KHÔNG đọc DB service khác. Đồng bộ CHỈ qua event NATS / HTTP nội bộ.
- **Consumer idempotent** (dedupe `event_id`, `ON CONFLICT`). **Producer best-effort** (lỗi publish chỉ log warning, KHÔNG raise, KHÔNG chặn nghiệp vụ).
- Payload theo `infra/nats/subjects.md` (business fields top-level + `event_id`/`event_version`/`occurred_at`). Dùng lại helper `build_*`, đổi payload/subject phải báo Backend Dev (Vu Quang Dung) trước.
- Chống loop: hr KHÔNG nghe lại event của chính nó; chỉ query nghe `hr.employee_profile.updated`; `occurred_at` mới nhất thắng.

### A.5 ĐỌC GÌ TRƯỚC KHI CODE (để không phá code / gây crash)
> **Quy trình bắt buộc:** trước khi sửa, đọc **(1) interface/Protocol ở `domain`** của thứ bạn đụng → **(2) test hiện có** của nó (hiểu hợp đồng đang được bảo vệ) → **(3) chỗ wire ở `composition`/`main.py`** → mới sửa `application`/`infrastructure`. Đọc test TRƯỚC giúp biết hành vi nào không được làm gãy.

**Đọc nền (mọi task):**
- `infra/nats/subjects.md` — hợp đồng event (source of truth). Đụng subject/payload phải báo Backend Dev.
- `config.yaml` **+** `config_schema.py` của service đang sửa — bộ đôi PHẢI khớp (rag-worker: `core_engine/config_schema.py`).
- `deploy/env/*.env` — env hiện hành (đổi cấu hình ở đây, không hardcode).
- `docker-compose.yml` — thứ tự `*-migrate` / `*-backfill` + `depends_on` (hiểu luồng khởi động trước khi đụng).

**Map nhanh "sửa gì → đọc gì":**
| Bạn định sửa | BẮT BUỘC đọc trước | Vì sao |
|--------------|---------------------|--------|
| Nghiệp vụ (use case) | interface ở `domain/` + test use case đó | Không gãy hợp đồng + chiều phụ thuộc |
| Adapter DB/Qdrant/HTTP/NATS | interface `domain/repositories/*` nó implement + test integration | Giữ đúng signature, không vỡ caller |
| Consumer/Publisher NATS | `subjects.md` + publisher/subscriber đối ứng ở service kia | Chống loop, payload đúng, idempotent |
| Config | `config.yaml` + `config_schema.py` cùng lúc | Tránh CI parity `extra_forbidden` |
| MCP tool | `app/tools/base.py` + `registry.py` + tool cùng loại | Giữ enabled-policy + không phá tool khác |
| query agent | `langgraph_state.py` → `langgraph_nodes.py` → `langgraph_edges.py` | Hiểu state/luồng trước khi đổi 1 node |

---

## PHẦN B — Từng việc

### T1 — Verify đồng bộ user→hr→query trên VM 🔴 (KHÔNG code mới)
📖 **Đọc trước:** `src/hr-service/app/infrastructure/user_events_subscriber.py` (luồng nhận `user.*`) · `src/hr-service/app/infrastructure/nats_publisher.py` (publish `hr.employee_profile.updated`) · `src/user-service/scripts/backfill_user_events.py` · `infra/nats/subjects.md` · block `user-backfill`/`*-migrate` trong `docker-compose.yml`. Hiểu luồng `user.* → hr provision → hr.employee_profile.updated → query` để verify đúng điểm.

✅ **Guard CD đã thêm:** `deploy-develop.yml` bước `5c` (block `if [ "$SMOKE_HR" = "true" ]`) — sau deploy gọi `POST http://localhost:8004/hr/query` intent `leave_balance` cho `SMOKE_UID`, assert 200 + `annual_remaining` là số; fail → rollback. Mỗi deploy tự kiểm sync user→hr.

Code đã merge (`5799eca`, `083ffc2`, `25d500d`). Verify thủ công thêm (1 lần cho chắc, gồm chiều hr→query mà CD chưa phủ):
1. Pipeline `deploy-develop.yml` chạy hết 3-phase (test → Docker Hub `dadlks08` → VM pull).
2. SSH VM `vsf-rag-demo-vm` (gcloud IAP tunnel, cần sudo docker). Backfill go-live:
   ```bash
   cd ~/DA08-VSF
   sudo docker compose run --rm --no-deps user-backfill   # log: "đã phát user.created cho N user"
   ```
3. **user→hr:** hỏi HR admin thật (`4f44e7f7…`) "số ngày phép còn lại của tôi" → ra **số thật**, không NO_INFO/404.
4. **hr→query:** đổi department 1 user → `psql` kiểm `query_svc.user_access_profile` có row cập nhật.
5. **chống loop:** đọc log hr — subscriber chỉ đăng ký `user.*`.

(Tùy chọn) đối soát định kỳ, không đọc chéo DB:
```bash
cd ~/DA08-VSF && bash deploy/scripts/install_user_backfill_cron.sh   # đổi lịch: CRON_SCHEDULE="0 */6 * * *" bash ...
```
**DONE:** admin thật ra số phép; user mới → hr tự có hồ sơ + query projection cập nhật; hr không loop; smoke pass.

### T2 — Tuning TRIAGE bớt CLARIFY 🔴
📖 **Đọc trước:** `src/query-service/app/application/langgraph_state.py` (state) → `langgraph_nodes.py` (node triage) → `langgraph_edges.py` (rẽ nhánh CLARIFY) → `intent_classifier.py` · `src/query-service/Docs/bug.md`. Hiểu state + điều kiện rẽ CLARIFY hiện tại TRƯỚC khi đổi ngưỡng, để không gãy nhánh khác.
- **Ở đâu:** node TRIAGE/classify trong agent LangGraph `query-service`.
- **Làm gì:** nới ngưỡng — câu policy đã rõ (vd "chính sách nghỉ phép hàng năm") KHÔNG rơi vào CLARIFY; giữ CLARIFY cho câu mơ hồ/thiếu chủ ngữ. Sửa qua prompt/threshold, KHÔNG đụng retrieval (đã xong `1b517ba`).
- **Test:** bộ câu mẫu (policy rõ → SUCCESS không CLARIFY; mơ hồ → vẫn CLARIFY). Verify luồng LLM thật trong container + đọc Langfuse trace `rag-query`.
- **DONE:** câu policy rõ trả thẳng `sources≥1`; câu mơ hồ vẫn hỏi lại; verify VM.

### T3 — Fix log INFO ra docker stdout 🟡
📖 **Đọc trước:** `src/rag-worker/app/interfaces/api/runtime.py` + `app/main.py` (chỗ cấu hình logging hiện tại) · `src/hr-service/app/main.py` · `config_schema.py` (nếu thêm key `log_level`). Tìm chỗ set root logger WARNING TRƯỚC khi đổi, đừng thêm `basicConfig` thứ hai (gây double-log/đè handler).
- **Làm gì:** set log level từ env (`LOG_LEVEL=INFO`) ở chỗ cấu hình logging từng service; handler ghi ra `stdout` (StreamHandler) để `docker logs` thấy; không hardcode WARNING; env vào `deploy/env/*.env`; giữ structured/JSON nếu đang dùng.
- **Test:** unit logging setup (level đọc đúng từ env); verify `docker logs <svc>` thấy INFO sau deploy.
- **DONE:** `docker logs` ra INFO trên VM, không phụ thuộc Langfuse để debug.

### T4 — Leave Request WRITE flow (HR + MCP) 🟡
> **CHẶN:** SA approve contract TRƯỚC khi merge. Feature-flag OFF mặc định.

📖 **Đọc trước:** `src/hr-service/docs/` + `src/mcp-service/docs/maintool/` (thiết kế đã chốt) · `src/hr-service/app/domain/repositories/hr_repository.py` + `app/infrastructure/db/postgres_hr_repository.py` + `migrations/versions/0001*,0002*` (KHÔNG đụng, thêm mới) · `src/mcp-service/app/tools/base.py` + `registry.py` + `hr_query.py` (mirror pattern proxy + enabled-policy) · `infra/nats/subjects.md` (subject mới cho đơn nghỉ — báo Backend Dev).

**HR Service:** migration **mới** (KHÔNG đụng `0001`/`0002`) cho đơn nghỉ; use case `create_leave_request` (validate qua `leave_balance`) + `approve_leave_request`; sau commit DB → publish event NATS **best-effort**; self-access (user tạo cho chính mình, duyệt cần quyền).
**MCP Service:** tool WRITE `create_leave_request` (`src/mcp-service/docs/maintool/`) proxy sang hr với `X-Internal-Token`, flag `TOOL_CREATE_LEAVE_REQUEST_ENABLED=0`; không ảnh hưởng `rag_search`/`hr_query`.
**Test:** happy; edge (phép không đủ → từ chối); failure (hr 4xx → lỗi rõ); best-effort (NATS lỗi → đơn vẫn lưu); self-access. Fake/stub.
**DONE:** flag ON staging → tạo/duyệt chạy thật; flag OFF → hành vi cũ y hệt; SA duyệt; CI + verify VM xanh.

### T5 — Tăng coverage test hr-service 🟡
📖 **Đọc trước:** `src/hr-service/app/api/routes.py` (7 intent) · `app/application/services/employee_profile_service.py` (logic + `_audit()` + self-access) · `app/infrastructure/db/postgres_hr_repository.py` · test mẫu `tests/test_hr_query_endpoint.py` + `tests/test_user_events_handler.py` (copy style Stub). Đọc để test ĐÚNG hành vi hiện có, không nới test cho qua.
- **Ở đâu:** `src/hr-service/tests/` (mirror cây `app/`).
- **Bổ sung test:** mỗi 7 intent READ (`leave_balance/leave_requests/attendance/onboarding/payroll/benefits/performance`) happy + NO_INFO; **audit path** 3 intent nhạy cảm ghi `_audit()`; **self-access** `WHERE user_id` (user A không đọc data user B); lazy auto-create (user chưa có → tạo `leave_balance` idempotent, không 404); Unicode tiếng Việt.
- **DONE:** phủ 7 intent + audit + self-access; `python -m pytest` xanh local + CI.

### T6 — MCP security hardening 🟡
📖 **Đọc trước:** `src/mcp-service/docs/security-hardening.md` · `src/mcp-service/app/tools/hr_query.py` (chỗ gắn `X-Internal-Token`) + `registry.py` (enabled-policy) + `app/core/config.py` · `src/hr-service/app/api/auth.py` (đầu nhận token phía hr). Đọc cả 2 đầu token TRƯỚC khi siết, tránh fail-closed sai làm gãy luồng đang chạy.
- **Ở đâu:** `src/mcp-service/docs/security-hardening.md`.
- **Làm gì:** `X-Internal-Token` MCP↔hr bắt buộc, so sánh constant-time (`hmac.compare_digest`), **fail-closed** khi thiếu/sai; giới hạn tool theo enabled policy ở prod; hr-service internal-only (không nginx public).
- **Test:** thiếu/sai token → từ chối; đúng → qua; tool disabled → không lộ trong discovery.
- **DONE:** auth nội bộ fail-closed có test; policy tool đúng ở prod config.

### T7 — Env user/document/query vào GitHub secret 🟡
📖 **Đọc trước:** `deploy/env/*.env` của rag/mcp/hr (mẫu convention đã chuẩn) · `.github/workflows/deploy-develop.yml` (cách load env) · `src/{user,document,query}-service/app/core/config.py` (env service đang đọc). So sánh để không bỏ sót key, không đổi tên biến đang dùng.
- **Làm gì:** đồng bộ convention env-từ-git như rag/mcp/hr — `deploy/env/*.env` commit thẳng, set qua PyNaCl API. Env trỏ Qdrant nội bộ `qdrant:6333` (KHÔNG cloud → 404 crash).
- **DONE:** 3 service còn lại lấy env từ git như nhóm rag/mcp/hr; deploy không provision secret tay.

### T8 — Tuning chất lượng chunk/caption (gap6–gap9) 🟢
📖 **Đọc trước:** `src/rag-worker/docs/gap` (gap6–gap9) · `src/rag-worker/app/application/use_cases/ingestion/ingest_document_use_case.py` (luồng chunk/caption/embed) · `config.yaml` + `core_engine/config_schema.py` (tham số chunk) · `tests/eval` (baseline đo). Chạy eval baseline TRƯỚC + SAU để chứng minh không hồi quy.
- **Ở đâu:** `src/rag-worker/` pipeline chunk/caption; docs `src/rag-worker/docs/gap`.
- **Làm gì:** cải thiện chunk + caption tăng độ chính xác retrieval; dùng `tests/eval` (validation corpus) đo trước/sau. KHÔNG chặn production.
- **DONE:** eval tốt hơn baseline, không hồi quy luồng ingest.

---

## Checklist tự review trước PR
- [ ] Đúng layer, không vi phạm chiều phụ thuộc.
- [ ] Test happy + edge + failure + (nếu có) idempotency/self-access; fail-trước-pass-sau.
- [ ] `config.yaml` ↔ `config_schema.py` đồng bộ (nếu đụng config).
- [ ] Env (nếu đổi) vào `deploy/env/*.env`.
- [ ] Feature mới có flag OFF mặc định; backward-compatible.
- [ ] `pytest` xanh local; CI unit + e2e xanh; luồng E2E đã (hoặc có kế hoạch) verify trên VM.

## Liên kết ngoài (nguồn chi tiết trong repo, không nằm trong folder này)
- Hợp đồng event: `infra/nats/subjects.md` · Mẫu Alembic chuẩn: `src/hr-service/migrations/env.py` + block `hr-migrate` trong `docker-compose.yml`
- Pattern Langfuse low-level: `src/query-service/app/infrastructure/observability/langfuse_tracing.py`
- Docs gap RAG: `src/rag-worker/docs/gap` · MCP WRITE tool: `src/mcp-service/docs/maintool/` · MCP security: `src/mcp-service/docs/security-hardening.md`
</content>
