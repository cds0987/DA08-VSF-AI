# SESSION HANDOFF — VSF RAG Chatbot (nối FE + sửa full flow)

**Cập nhật:** 2026-06-10. **Branch:** `nguyendev` (push lên `develop` để deploy). **Commit gần nhất:** xem `git log`.

## 1. Bối cảnh hạ tầng (QUAN TRỌNG — đọc trước)
- **VM production:** `vsf-rag-demo-vm` (project `vsf-rag-chatbot-dev`, zone `asia-southeast1-a`), IP công khai **34.158.47.236**. App dir trên VM: `/home/tranhuugiahuynb/DA08-VSF`. Container prefix `da08-vsf-*-1`.
- **Truy cập VM:** SSH cổng 22 bị chặn. Dùng IAP + chạy dưới root (user thường không có quyền docker/cd):
  ```
  gcloud compute ssh vsf-rag-demo-vm --project vsf-rag-chatbot-dev --zone asia-southeast1-a --tunnel-through-iap --quiet --command "..."
  ```
  Lệnh cần `cd`/đụng file app: đóng gói script → `echo <base64> | base64 -d | sudo bash` (xem ví dụ trong lịch sử). `sudo docker ...` (user thường không có docker perm).
- **Deploy:** push `nguyendev:develop` → workflow `.github/workflows/deploy-develop.yml`. Detect dùng `base=github.event.before` nên **push chỉ đụng 1 service → chỉ build+deploy service đó, KHÔNG chạy full validate** (nhanh ~3-4 phút). Đổi `.github/workflows/**` → FORCE full. Có cờ `skip_tests` (workflow_dispatch) / `[skip-tests]` trong commit msg.
- **nginx config nướng vào image** (`nginx/Dockerfile`), KHÔNG bind-mount → sửa tay nginx.conf trên VM vô tác dụng. Đổi nginx phải qua git→CI.
- **Theo dõi CI (không có gh CLI):** lấy PAT qua `git credential fill`, curl `api.github.com/repos/lehuuhung2001/DA08-VSF/actions/runs`.
- **Login demo (admin):** `admin@company.com` / `***REDACTED-SEED-ADMIN-PW***` (role admin, có ở `src/user-service/README.md`).
- **FE:** chat ở `/` (http://34.158.47.236/), admin ở `/admin/`. Cùng origin nginx :80 → không CORS.

## 2. Công cụ test UI tự động (Playwright Python — đã cài)
- `python tmp-ui-check/ui_check.py` → tự login admin + chat, duyệt mọi trang, upload, hỏi RAG, **bắt console/page/network error + chụp ảnh** vào `tmp-ui-check/*.png`. Chạy với `PYTHONUTF8=1` (Windows console cp1252 vỡ tiếng Việt).
- Query RAG trực tiếp (SSE): xem `tmp-ui-check/q5.py` / `q6.py` (login → POST `/api/query/query` body `{"question","user_id"}`, user_id decode từ JWT).
- `tmp-ui-check/` là tooling tạm, **chưa commit** (gitignore nó nếu muốn giữ sạch).

## 3. Đã sửa xong session này (đều qua code→CI, trừ 1 ngoại lệ)
Mọi lỗi network/console đã hết (full UI review: **network 0, console 0, page-error 0**). Upload→index→list, dashboard, audit, users, notifications, chat-stream đều chạy.
- **FE:** `queryService` `$fetch`→`axiosClient` (hết 404 `/admin/api/query`); `documentService.listDocuments` `get('')`→`get('/')` + nginx exact-match `/api/documents/`→`/documents` (hết list trả HTML do 307).
- **user-service & document-service:** thêm `GET /audit-logs` (repo `.list()` + schema + router; document-service route khai báo TRƯỚC `/{document_id}`).
- **query-service (chuỗi 5 lỗi):**
  1. Config crash (prod đòi llm_guard/langfuse) → `config.py` linh hoạt: thiếu key→off, không crash.
  2. Crash JetStream subscribe (`hr.employee_profile.updated` chưa có stream) → `nats_subscriber.py` tự ensure_stream + subscribe resilient.
  3. 500 DSN `postgresql+psycopg` → `_asyncpg_url` (postgres_document_access_repo.py) strip mọi `+driver`.
  4. 500 bảng `query_svc.*` chưa tồn tại → `migrate.py` auto-run on startup + `Dockerfile COPY migrations`.
  5. RAG threshold hardcode 0.70/0.75 trong `act_node` → config-driven qua `AgentState.rag_score_threshold` + hạ default 0.35.
- **NGOẠI LỆ (sửa tay trên VM, KHÔNG qua CI):** `MCP_INTERNAL_TOKEN` trong `deploy/env/query-service.env` rỗng → mcp-service trả 401 → đã set = token mcp-service (43 ký tự). **Lỗ hổng:** env của user/document/query KHÔNG provision qua CI (chỉ rag/mcp/hr). Nên vá: đưa 3 env này vào GitHub secret như rag/mcp/hr.

## 4. VẤN ĐỀ ĐANG MỞ — RAG retrieval không ra kết quả
Chat hỏi (vd "số ngày nghỉ phép năm") → trả lời **"Mình không tìm thấy thông tin phù hợp trong tài liệu nội bộ"**, sources=0.
- Hạ threshold KHÔNG đủ vì: (a) **`RAG_SCORE_THRESHOLD=0.70` set trong env VM `query-service.env`** override default code 0.35 — cần đổi env (hoặc xoá dòng đó) HOẶC quan trọng hơn:
- **`langgraph_act_error` lặp lại trong log query-service** → `act_node` GỌI rag_search nhưng **execution throw exception** (bị bắt ở `langgraph_nodes.py:545`). mcp-service chỉ thấy `ListToolsRequest`, KHÔNG có `CallToolRequest` → lỗi xảy ra TRƯỚC khi chạm mcp.
- `allowed_doc_ids` KHÔNG rỗng (admin bypass `can_access_document` → 13 docs; bảng `query_svc.document_access` có 13 rows).

### Bước tiếp theo (làm ngay ở session mới):
1. **Lấy nội dung lỗi `langgraph_act_error`** — error string nằm trong `extra={"error": str(exc)}` (logger line 548), docker plain log KHÔNG hiện. Cách lấy:
   - Xem New Relic (NEW_RELIC_* đã cấu hình, app `vsf-query-service`), HOẶC
   - Tạm sửa `act_node` except (line 545-549) thêm `logger.error("act_err_detail", exc_info=True)` hoặc `import traceback; logger.error(traceback.format_exc())` → deploy → query → đọc traceback.
2. Khả năng cao lỗi ở `_make_rag_search._rag_search` → `client.rag_search(...)` (MCPStreamableHttpClient ở `mcp_client.py`) — parse/serialize/session error. Warmup cũng fail (`mcp_tools_warmup_failed`: `MultiServerMCPClient` dùng như context manager — API langchain-mcp-adapters 0.1.0 đổi; ở `langchain_mcp_client.py:83`) nhưng đó chỉ là warmup mô tả tool, KHÔNG phải đường execute. Vẫn nên sửa cho sạch: `client = MultiServerMCPClient(...); tools = await client.get_tools()`.
3. Sau khi rag_search chạy được: chỉnh `RAG_SCORE_THRESHOLD` (env VM hiện 0.70) xuống ~0.35 để chunk lọt; verify "số ngày nghỉ phép" ra câu trả lời + sources từ `leave_policy.md`.

## 5. Kiến trúc nhanh (tham chiếu)
- Query flow: FE `/api/query/query` (SSE) → query-service LangGraph agent (`orchestration.py` → `langgraph_nodes.py`: triage→think→act→answer) → `act_node` gọi MCP `rag_search`/`hr_query` → mcp-service → Qdrant (index `rag_chatbot__te3s__d1536`, embedding text-embedding-3-small). RERANK_PROVIDER=none.
- Upload flow (CHẠY OK): FE `/api/documents/upload` → document-service → GCS + NATS → rag-worker index → Qdrant + cập nhật status `indexed`.
- Triage (`langgraph_nodes.py:153`) dùng LLM gpt-4o-mini phân loại off_topic/clarify/in_scope — đôi khi xếp câu HR rõ ràng vào "clarify" (hỏi lại) thay vì in_scope; đây là tuning prompt `TRIAGE_SYSTEM_PROMPT` (cân nhắc sau).

## 6. Lệnh hữu ích
```
# Test full UI
PYTHONUTF8=1 python tmp-ui-check/ui_check.py
# Log query-service trên VM
gcloud compute ssh vsf-rag-demo-vm --project vsf-rag-chatbot-dev --zone asia-southeast1-a --tunnel-through-iap --quiet --command "sudo docker logs --tail 50 da08-vsf-query-service-1 2>&1 | tail -50"
# Recreate 1 service trên VM (LƯU Ý: đổi IP container -> phải restart nginx sau đó)
#   sudo docker restart da08-vsf-nginx-1   (để nginx re-resolve IP mới)
```
