---
service: mcp-service
path: src/mcp-service
last-verified: 59551e39 (2026-06-29)
code-refs:
  - src/mcp-service/app/main.py
  - src/mcp-service/app/interfaces/mcp_server.py
  - src/mcp-service/app/core/config.py
  - src/mcp-service/app/core/search.py
  - src/mcp-service/app/tools/base.py
  - src/mcp-service/app/tools/registry.py
  - src/mcp-service/app/tools/rag_search.py
  - src/mcp-service/app/tools/hr_query.py
  - src/mcp-service/app/tools/leave_write.py
  - src/mcp-service/app/tools/leave_approvals.py
  - src/mcp-service/app/tools/leave_types.py
  - src/mcp-service/app/tools/resolve_date.py
  - src/mcp-service/config.yaml
---
# MCP Service

## Trách nhiệm
Server MCP (FastMCP, transport **Streamable HTTP**, `stateless_http=True`, `json_response=True`) expose một bộ tool cho `query-service` (orchestrator) gọi. Là tầng **THIN / proxy**: KHÔNG sở hữu embed model, collection contract hay HR data — embed + vector search là việc của rag-worker (`POST /api/search`); HR data là việc của hr-service. mcp-service chỉ điều phối, rerank/diversify (rag_search), và proxy HTTP có `X-Internal-Token`.

Khởi động: `load_settings()` → `enforce_production_auth()` (fail-closed: ở `app_env` prod/production mà thiếu `internal_token` → raise) → `build_mcp()` đăng ký tool theo config → `verify()` từng tool (rồi đóng client để serve loop tự lazy-init) → serve bằng uvicorn trên Starlette app (`mcp.streamable_http_app()`), gắn `InternalTokenAuthMiddleware` nếu có token. Endpoint: `http://<host>:<port>/mcp` (default `0.0.0.0:8003`).

Auth: middleware so khớp header `X-Internal-Token` (hằng-thời-gian `hmac.compare_digest`), sai/thiếu → 401. Token trống = auth TẮT (chỉ được phép ở dev).

## Tools cung cấp
Đăng ký qua `Registry` (built-in mặc định BẬT; entry-point `mcp_service.tool` mặc định TẮT). 6 tool entry trong code (`app/tools/__init__.py`); một entry có thể expose nhiều MCP function.

| Tool entry | MCP function | Input | Output | Backend |
|---|---|---|---|---|
| `rag_search` | `rag_search` | `query: str`, `document_ids?: list[str]`, `top_k?: int` | `{results: [chunk_id, document_id, document_name, caption, child_text, parent_text, heading_path, score, page_number, source_gcs_uri, markdown_gcs_uri]}` | rag-worker `POST /api/search` |
| `hr_query` | `hr_query` | `user_id: str` | toàn bộ hồ sơ HR (dict) | hr-service `POST /hr/profile` |
| `leave_write` | `create_leave_request` | `user_id, leave_type, start_date, end_date, reason="", idempotency_key=""` | đơn vừa tạo (status pending) | hr-service `POST /hr/leave-requests` |
| `leave_write` | `update_leave_request` | `user_id, request_id, leave_type, start_date, end_date, reason="", idempotency_key=""` | đơn kết quả | hr-service `PATCH /hr/leave-requests/{id}` |
| `leave_write` | `cancel_leave_request` | `user_id, request_id` | đơn sau hủy | hr-service `POST /hr/leave-requests/{id}/cancel` |
| `leave_approvals` | `leave_approvals` | `user_id: str` (= approver) | `{items:[...], count}` | hr-service `GET /hr/leave-requests/pending-approval?approver_user_id=` |
| `leave_types` | `leave_types` | `user_id=""` (bỏ qua) | `{...}` danh mục loại nghỉ | hr-service `GET /hr/leave-types` |
| `resolve_date` | `resolve_date` | `kind, weekday?, week_offset=0, days?, span_days?, date=""` | `{date, weekday_vi, today}` (+`start_date/end_date` khi span>1) hoặc `{error}` | pure-compute (không gọi service) |

Ghi chú:
- `user_id` do query-service inject từ JWT — KHÔNG tin LLM. Tool tự lọc/scope theo user_id.
- `hr_query`: MCP function gọi `/hr/profile` trả TOÀN BỘ 7 section (LLM tự nhặt phần liên quan). `_call()` (granular `/hr/query` theo intent, tập `MVP_INTENTS`: leave_balance/leave_requests/attendance/onboarding/payroll/benefits/performance) chỉ giữ cho backward-compat + test, KHÔNG expose qua MCP.
- `leave_write`: chỉ proxy, KHÔNG validate nghiệp vụ (cap/quỹ/transaction là hr-service). 4xx → trả lỗi có cấu trúc `{ok:false, status_code, error}`; 5xx → raise. Approve/reject KHÔNG ở MCP (là REST có xác nhận ở FE).
- `rag_search`: lấy `top_k_candidates` ứng viên từ rag-worker → rerank (`impl`: none/lexical/llm, fallback NoopReranker giữ vector-order) → áp `rerank_threshold` → nếu `rerank_max_per_doc>0` thì rerank pool rộng (`final_k * diversity_pool`) rồi `diversify_by_document`. `final_k = clamp(top_k|rerank_top_k, 1, top_k_candidates)`.
- `resolve_date`: deterministic, giờ `Asia/Ho_Chi_Minh`; weekday dùng token VN (`thu_2..thu_7`, `chu_nhat`); có past-date guard.

## Luồng
`query-service (orchestrator/MCP client)` → HTTP `/mcp` (Streamable HTTP, header `X-Internal-Token`) → tool MCP → backend:
- `rag_search` → rag-worker `POST /api/search` → rerank/diversify nội bộ.
- `hr_query` / `leave_*` → hr-service (`POST /hr/profile`, `/hr/leave-requests*`, `GET /hr/leave-types`, `/hr/leave-requests/pending-approval`) với `X-Internal-Token`.
- `resolve_date` → tính tại chỗ, không ra ngoài.

## Config / ENV
Nguồn: `config.yaml` (profile `${PIPELINE_PROFILE:-baseline}`, env-substitution `${VAR:-default}`).
- Server: `MCP_HOST` (0.0.0.0), `MCP_PORT` (8003), `LOG_LEVEL` (INFO), `APP_ENV` (development), `MCP_INTERNAL_TOKEN` (trống=auth tắt).
- rag_search: `TOOL_RAG_SEARCH_ENABLED` (1), `RAG_WORKER_URL` (http://rag-worker:8000), `RAG_SEARCH_TIMEOUT_SECONDS` (30); reranker `RERANK_PROVIDER` (lexical), `RERANK_MODEL`, `RERANK_BASE_URL`/fallback `EMBED_BASE_URL`, `RERANK_API_KEY`/`AIROUTER_INTERNAL_TOKEN` (rerank đi qua ai-router), `RERANK_TIMEOUT_SECONDS`, `RERANK_BATCH_SIZE` (8), `RERANK_PASSAGE_CHARS` (800); retrieval `SEARCH_TOP_K` (20), `RERANK_TOP_K` (5), `RERANK_THRESHOLD` (0.05), `RERANK_MAX_PER_DOC` (0), `RERANK_DIVERSITY_POOL` (3).
- HR tools (mặc định TẮT): `TOOL_HR_QUERY_ENABLED`, `TOOL_LEAVE_APPROVALS_ENABLED`, `TOOL_LEAVE_TYPES_ENABLED`, `TOOL_LEAVE_WRITE_ENABLED` (=0); chung `HR_SERVICE_URL` (http://hr-service:8004), `HR_SERVICE_INTERNAL_TOKEN`.
- `resolve_date`: `TOOL_RESOLVE_DATE_ENABLED` (1).

## Phụ thuộc
- **rag-worker** `/api/search` (rag_search).
- **hr-service** (hr_query, leave_write, leave_approvals, leave_types) qua `X-Internal-Token`.
- **ai-router** gateway cho rerank LLM/cohere (qua `RERANK_BASE_URL` + `AIROUTER_INTERNAL_TOKEN`).
- Lib: `mcp` (FastMCP), `httpx`, `uvicorn`, `starlette`, `pyyaml`.
- Client: **query-service** (orchestrator MCP).

## Code map
- Entrypoint: [app/main.py](src/mcp-service/app/main.py)
- MCP server / transport / auth: [app/interfaces/mcp_server.py](src/mcp-service/app/interfaces/mcp_server.py)
- Config loader: [app/core/config.py](src/mcp-service/app/core/config.py) · [config.yaml](src/mcp-service/config.yaml)
- Search orchestration + diversify: [app/core/search.py](src/mcp-service/app/core/search.py) · rerank [app/core/rerank.py](src/mcp-service/app/core/rerank.py)
- Tool registry: [app/tools/registry.py](src/mcp-service/app/tools/registry.py) · [app/tools/base.py](src/mcp-service/app/tools/base.py)
- Tools: [rag_search](src/mcp-service/app/tools/rag_search.py) · [hr_query](src/mcp-service/app/tools/hr_query.py) · [leave_write](src/mcp-service/app/tools/leave_write.py) · [leave_approvals](src/mcp-service/app/tools/leave_approvals.py) · [leave_types](src/mcp-service/app/tools/leave_types.py) · [resolve_date](src/mcp-service/app/tools/resolve_date.py)
