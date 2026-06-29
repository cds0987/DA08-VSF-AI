---
service: query-service
path: src/query-service
last-verified: 59551e39 (2026-06-29)
code-refs:
  - app/interfaces/api/main.py
  - app/interfaces/api/routers/query.py
  - app/interfaces/api/sse.py
  - app/interfaces/api/schemas/query.py
  - app/application/use_cases/query/orchestration.py
  - app/agents/graph_builder.py
  - app/agents/sse_contract.py
  - app/agents/manifest.py
  - app/agents/agents.yaml
  - app/agents/planners/base.py
  - app/infrastructure/config.py
  - app/interfaces/api/routers/{conversations,feedback,admin,leave,notifications}.py
---

# Query Service

FastAPI (`app.interfaces.api.main:app`, title "Query Service", `0.1.0-phase1`). Lifespan khởi
động/dừng NATS subscriber manager. CORS từ `cors_origins`. Đăng ký router: query, notifications,
conversations, feedback, leave, admin + `/health`.

## Trách nhiệm
- Nhận câu hỏi người dùng -> điều phối LLM (MOSA Orchestrator-Workers hoặc legacy route) -> stream
  câu trả lời + trích dẫn nguồn qua SSE.
- ACL doc-level (lọc tài liệu user được phép trước & sau RAG), rate-limit + concurrency cap/user,
  lịch sử hội thoại (memory: recent window + summary + task-state), feedback, notifications,
  proxy CRUD đơn nghỉ phép sang hr-service.

## API / giao diện
Đường dẫn dưới đây là path TRONG service; ingress/gateway có thể thêm prefix.

- **POST /query** — chat SSE chính (`text/event-stream`). Body `QueryRequest`: `question` (1..500),
  `user_id` (phải khớp user JWT, lệch -> 403), `conversation_id?`, `trace_session?`,
  `conversation_title?`, `document_ids?`. Rate-limit + concurrency check TRƯỚC mọi I/O
  (429 nếu vượt, 503 nếu limiter chết). Header `X-CI-Smoke` -> gom trace vào session "ci-smoke".
- **GET /conversations**, **GET /conversations/{id}** (paginated, 404 nếu thiếu),
  **POST /conversations/{cid}/messages/{mid}/actions** (lưu trạng thái action vd đơn nghỉ; 501 nếu repo
  không hỗ trợ), **PATCH /conversations/{id}** (đổi tên), **DELETE /conversations/{id}**,
  **DELETE /conversations** (xoá toàn bộ).
- **POST /feedback** — chấm điểm session (`score` 1|-1), nếu có `trace_id` thì score trace observability.
- **GET /notifications** — SSE realtime (keep-alive ~25s); **/notifications/history** (paginated,
  `unread_only`), **/notifications/unread-count**, **POST /{id}/read**, **DELETE /{id}** (204),
  **POST /dev/mock-notifications/doc-new** (DEV-ONLY, admin + `enable_dev_endpoints`).
- **/leave-requests** (prefix): **POST ""** tạo đơn, **POST /{id}/cancel**, **GET /pending-approval**,
  **GET /mine**, **POST /{id}/approve**, **POST /{id}/reject**, **GET /{id}** — proxy sang hr-service
  bằng `X-Internal-Token`, user_id từ JWT.
- **GET /admin/metrics** — admin-only, range `from`/`to`.
- **GET /health** — kiểm tra DB/Redis/MCP-circuit/NATS/auth/LLM; 503 + `degraded_reasons` nếu suy giảm.

### Luồng SSE (`format_sse` = `data: <json>\n\n`)
Hợp đồng 1-nguồn ở `sse_contract.py` (`validate_event` fail-safe: prod chỉ log cảnh báo).
- `phase` hợp lệ: `thinking` (+status), `acting` (+tool/tool_args), `observing` (+tool_result_summary),
  `generating` (+token), `plan` (+route, steps[]), `step` (+step_id, status), `thought` (+node, text),
  `model_used` (+node, model). `node` ∈ {orchestrate, plan, think, act, verify, answer}.
- Token câu trả lời: event mang `token`.
- **done-event** (bắt buộc đủ `DONE_REQUIRED` = `done`, `session_id`, `sources` — thiếu -> FE treo).
  Thực tế còn: `message_id`, `outcome` (enum Outcome 1..6), `agent_mode`, `retrieved`, `trace_id`
  (nếu tracer), `cached`/`fallback` ở vài path. Kênh nội bộ `_usage`/`_answer` bị pop trước khi gửi FE.

## Luồng MOSA
2 path trong `QueryOrchestrationUseCase.stream` -> `_stream_inner`:

1. **orchestrator_workers** (`_stream_orchestrator`) — bật khi `agent_mode==orchestrator_workers` +
   planner + make_model có sẵn. LangGraph (`build_orchestrator_graph`):
   `orchestrate` (planner sinh `Plan` = route + DAG steps, stream reasoning live chống dead-air;
   strip role `synthesize_recommend`+`analyze` khỏi DAG khi route≠light) ->
   fan-out `worker` song song (`max_workers_per_level`, mỗi role qua `AGENT_REGISTRY`, timeout) ->
   `join` (barrier) -> `verify_answer`. `verify_answer` GỘP analyze+verify+answer trong 1 LLM call:
   tự quyết `<<NEED_MORE>>` -> replan (`orchestrate`, tối đa `max_replan`) khi `verify_before_synthesize`
   bật; đủ -> stream câu trả lời + cite [N]. leave_action passthrough JSON verbatim (FE render form).
   Memory: load `MemoryContext` (dialogue+summary+task_state+working_set) cho planner đa lượt; ghi
   working-set + task_state sau lượt. Fail-closed: mọi lỗi -> done NO_INFO + câu xin lỗi, không raise.
   Guard `_is_raw_data_leak` chặn output worker thô lọt ra user.
2. **legacy** (mặc định) — `_choose_route` (RouteDecisionProvider/ToolDecisionClient + MCP list_tools)
   -> nhánh: clarification/identity/out_of_scope/off_topic (direct response), non-SUCCESS (fallback),
   `hr_query`, `rag_search` (`_handle_rag`: ACL pre+post filter, semantic cache, stream answer cite [N]),
   hoặc generic tool. Triage/intent: `app/application/intent_classifier.py` (mode hybrid: rule+embedding+LLM).

Roles (module trong `agents/roles/`): `rag_retrieve`, `hr_lookup`, `analyze`, `leave_action`,
`synthesize_recommend`, `critic`(disabled). Tập active runtime do `agents.yaml` quyết.

## Config / ENV (`app/infrastructure/config.py`, prefix env tên field hoa)
- Modes: `auth_mode`, `mcp_mode`, `nats_mode`, `llm_mode` (production cấm `mock`); `rate_limiter_mode`
  (production buộc `redis`); `enable_dev_endpoints` (cấm true ở production).
- Agent: `agent_mode` (rỗng=theo manifest; `orchestrator_workers` bật MOSA), `use_langgraph`,
  `agent_recent_k`, `summary_enabled`/`title_enabled`, `agent_split_answer`, `agent_merged_reason`,
  `agent_verify_sufficiency`, `llm_profiles_path`.
- LLM/AI-Router: `openai_base_url` (set -> route qua ai-router; rỗng -> OpenAI thẳng),
  `airouter_internal_token`, `llm_model_adapter` (responses|chat), `llm_capability`/`intent_capability`/
  `guardrail_capability`/`summary_capability`, `openai_llm_model` (gpt-5.4-nano).
- RAG: `rag_top_k`(8), `rag_result_limit`(3), `rag_score_threshold`(0.75), semantic cache ttl/threshold.
- Memory: `memory_enabled`, `memory_recent_n`, `memory_summarize_after`.
- Rate-limit: per-user(20)/per-IP(60)/global(600) per phút, `query_max_concurrent_per_user`(3).
- MCP pool: `mcp_persistent_session`, `mcp_session_pool_size`(16), circuit breaker, tool-cache ttl.
- Observability: `observability_mode` (langfuse,langsmith — lọc backend thiếu key), model-price catalog.
- `agents.yaml` ship `mode: react` (MOSA default-OFF), `planner: orchestrator_workers`,
  `verify_before_synthesize: true`, `max_replan: 1`, `worker_timeout_seconds: 60`.

## Phụ thuộc
- **AI Router** (`openai_base_url` http://ai-router:8010/v1) — mọi LLM/embedding khi route bật.
- **MCP service** — `rag_search`, `hr_query`, tool discovery (`list_tools`/`call_tool`), persistent session pool.
- **hr-service** (REST) — write/duyệt đơn nghỉ phép qua `X-Internal-Token`.
- **NATS/JetStream** — subscriber notifications + event đồng bộ access profile (department).
- **Postgres** (asyncpg, DSN qua `asyncpg_dsn`) — conversations/messages/feedback/notifications, ACL doc-ids.
- **Redis** — rate limiter + concurrency slot (production).
- **Langfuse / LangSmith** — trace (cost tính ở AI Router, không ở đây).

## Code map
- Entrypoint: [main.py](src/query-service/app/interfaces/api/main.py)
- Chat SSE route: [query.py](src/query-service/app/interfaces/api/routers/query.py) · [sse.py](src/query-service/app/interfaces/api/sse.py) · [schemas/query.py](src/query-service/app/interfaces/api/schemas/query.py)
- Orchestration: [orchestration.py](src/query-service/app/application/use_cases/query/orchestration.py)
- MOSA graph: [graph_builder.py](src/query-service/app/agents/graph_builder.py) · [manifest.py](src/query-service/app/agents/manifest.py) · [agents.yaml](src/query-service/app/agents/agents.yaml) · [planners/base.py](src/query-service/app/agents/planners/base.py)
- SSE contract: [sse_contract.py](src/query-service/app/agents/sse_contract.py)
- Config: [config.py](src/query-service/app/infrastructure/config.py)
- Routers khác: [conversations.py](src/query-service/app/interfaces/api/routers/conversations.py) · [feedback.py](src/query-service/app/interfaces/api/routers/feedback.py) · [leave.py](src/query-service/app/interfaces/api/routers/leave.py) · [notifications.py](src/query-service/app/interfaces/api/routers/notifications.py) · [admin.py](src/query-service/app/interfaces/api/routers/admin.py)
