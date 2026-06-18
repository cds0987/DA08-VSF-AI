# Query Service — Tài liệu kỹ thuật

> Cập nhật: 2026-06-17 | Branch: `query-service/eval`

---

## 1. Query Service là gì?

Query Service là **cửa vào duy nhất** cho mọi câu hỏi của người dùng cuối trong hệ thống VinSmartFuture RAG Chatbot. Nó đóng vai trò **orchestrator** — nhận câu hỏi từ frontend qua HTTP, phân loại, chọn tool phù hợp, gọi backend (mcp-service, hr-service), sau đó stream câu trả lời về dạng **Server-Sent Events (SSE)**.

**Nhiệm vụ cốt lõi:**
- Xác thực người dùng và kiểm tra rate limit (4 lớp: user / IP / global / concurrency)
- Phân loại câu hỏi (triage): shortcut deterministic, SAFETY, REFUSE, CLARIFY, META, ALLOW
- Thực hiện ACL: chỉ truy vấn tài liệu người dùng được phép xem
- Gọi tool qua MCP protocol (rag_search / hr_query / leave_approvals / resolve_date / leave_types / generic)
- Stream câu trả lời từng token về frontend
- Lưu lịch sử hội thoại, quản lý thông báo, proxy đơn nghỉ phép sang hr-service

---

## 2. Cấu trúc thư mục

```
src/query-service/
├── app/
│   ├── domain/                         # Lớp nghiệp vụ thuần túy (không phụ thuộc framework)
│   │   ├── entities/
│   │   │   ├── conversation.py         # Entity Conversation, Message, ConversationContext
│   │   │   └── notification.py         # Entity Notification
│   │   ├── repositories/               # Interface (Protocol) — định nghĩa contract
│   │   │   ├── conversation_repository.py
│   │   │   ├── document_access_repository.py
│   │   │   ├── notification_repository.py
│   │   │   └── user_access_profile_repository.py
│   │   └── outcome.py                  # Enum Outcome: REFUSE/CLARIFY/NO_INFO/OFF_TOPIC/SUCCESS/ERROR
│   │
│   ├── application/                    # Use-case và orchestration logic
│   │   ├── ports.py                    # Protocol interfaces: MCPToolClient, LLMStreamingClient, SemanticCache…
│   │   ├── tools.py                    # TOOL_DEFINITIONS (OpenAI schema)
│   │   ├── prompts.py                  # TRIAGE_SYSTEM_PROMPT + AGENT_SYSTEM_PROMPT + build_agent_system_prompt()
│   │   ├── shortcuts.py                # classify_shortcut() — 9 loại shortcut deterministic
│   │   ├── route_decision.py           # RouteDecision dataclass + normalize/coerce logic
│   │   ├── tool_decision.py            # ToolDecision dataclass + VALID_TOOL_NAMES
│   │   ├── query_router.py             # QueryRouter — intent classifier → route decision (legacy path)
│   │   ├── intent_classifier.py        # HybridIntentClassifier (rule + embedding + LLM)
│   │   ├── langgraph_state.py          # AgentState TypedDict + AgentPhase enum + create_initial_state()
│   │   ├── langgraph_edges.py          # Conditional edges: route_entry / route_after_triage / route_after_think / route_after_act
│   │   ├── langgraph_nodes.py          # shortcut_node / triage_node / think_node / act_node / observe_node / answer_node
│   │   ├── langgraph_agent.py          # build_langgraph_agent() — compile LangGraph graph
│   │   └── use_cases/query/
│   │       └── orchestration.py        # QueryOrchestrationUseCase — điều phối toàn bộ luồng xử lý
│   │
│   ├── infrastructure/                 # Adapter, client, repo cụ thể
│   │   ├── config.py                   # Settings (pydantic-settings, đọc .env)
│   │   ├── auth/
│   │   │   └── auth_service.py         # AuthService: mock / JWT / user-service HTTP
│   │   ├── cache/
│   │   │   ├── semantic_cache.py       # InMemorySemanticCache (bag-of-words cosine, TTL)
│   │   │   ├── rate_limiter.py         # RateLimiter: in-memory / Redis sliding window (4 lớp)
│   │   │   └── redis_access_cache.py   # Redis-backed ACL document access cache
│   │   ├── db/
│   │   │   ├── dsn.py                  # to_asyncpg_dsn() — chuẩn hoá DSN một nguồn duy nhất
│   │   │   ├── migrate.py              # Migration runner fail-fast (dùng khi startup)
│   │   │   ├── postgres_conversation_repo.py           # asyncpg, schema query_svc
│   │   │   ├── postgres_document_access_repo.py
│   │   │   ├── postgres_notification_repo.py
│   │   │   ├── postgres_user_access_profile_repo.py
│   │   │   ├── mock_conversation_repo.py               # In-memory (test/dev)
│   │   │   ├── mock_document_access_repo.py
│   │   │   ├── mock_notification_repo.py
│   │   │   ├── mock_user_access_profile_repo.py
│   │   │   └── mock_data.py            # MOCK_DOCUMENTS, MOCK_HR_DATA
│   │   ├── external/
│   │   │   ├── routed_openai.py        # build_routed_openai() + route_model() — helper dựng AsyncOpenAI route-aware
│   │   │   ├── langchain_chat_adapter.py       # OpenAIChatModel — Chat Completions adapter (CANONICAL)
│   │   │   ├── langchain_responses_adapter.py  # OpenAIResponsesChatModel — Responses API (LEGACY kill-switch)
│   │   │   ├── mcp_client.py           # MockMCPClient + MCPStreamableHttpClient (circuit breaker)
│   │   │   ├── langchain_mcp_client.py # LangChainMCPToolsLoader — dynamic tool discovery
│   │   │   ├── openai_client.py        # OpenAIStreamingClient — stream_answer() (legacy path)
│   │   │   ├── hr_leave_client.py      # HRLeaveClient — proxy đơn nghỉ sang hr-service
│   │   │   ├── tool_decision_client.py # OpenAIToolDecisionClient (deprecated)
│   │   │   └── intent_ai_client.py     # OpenAIIntentLLMClient, TokenHashIntentEmbeddingClient
│   │   ├── guardrails/
│   │   │   └── llm_guard_service.py    # NoOpInputGuardrail / LlmApiInputGuardrail / RegexPiiOutputGuardrail
│   │   ├── messaging/
│   │   │   ├── nats_events.py          # Event schemas + QueryNatsEventHandler
│   │   │   ├── nats_subscriber.py      # NatsSubscriberManager (subscribe 3 topic, DLQ poison-message)
│   │   │   └── notification_service.py # NotificationService
│   │   ├── observability/
│   │   │   ├── langfuse_tracing.py     # LangfuseTracer + CompositeTracer (fan-out)
│   │   │   ├── langsmith_tracing.py    # LangSmith RunTree tracer
│   │   │   ├── price_catalog.py        # ModelPriceCatalog — tính cost từ model_prices.json
│   │   │   └── data/
│   │   │       └── model_prices.json   # OpenRouter price catalog (bundled at build)
│   │   └── sse/
│   │       └── connection_manager.py   # SSE connection manager (online user tracking)
│   │
│   └── interfaces/api/                 # HTTP layer (FastAPI)
│       ├── main.py                     # App entry, lifespan, CORS, route registration
│       ├── dependencies.py             # Dependency injection (lru_cache singletons)
│       ├── routers/
│       │   ├── query.py                # POST /query → SSE stream
│       │   ├── conversations.py        # GET/PATCH/DELETE /conversations
│       │   ├── notifications.py        # GET/POST /notifications
│       │   ├── leave.py                # POST/GET /leave-requests (proxy → hr-service)
│       │   ├── feedback.py             # POST /feedback
│       │   └── admin.py                # Admin endpoints (dev only)
│       ├── schemas/                    # Pydantic request/response schemas
│       └── sse.py                      # format_sse() helper
│
├── tests/                              # pytest (asyncio, ASGI transport)
│   ├── conftest.py                     # Fixtures, mock tokens, parse_sse()
│   ├── test_query.py                   # SSE stream shape, validation
│   ├── test_acl.py                     # ACL enforcement
│   ├── test_triage.py                  # Triage node 5-label unit tests
│   ├── test_tool_discovery.py          # Dynamic tool discovery
│   ├── test_llm_architecture_enforcement.py  # GATE 1/1b/2/3 — kiến trúc LLM bắt buộc
│   ├── test_chat_adapter_contract.py   # Contract test cho OpenAIChatModel
│   ├── test_dsn_normalization.py       # DSN chuẩn hoá
│   ├── test_nats_poison_message.py     # NATS DLQ + poison-message
│   ├── test_notification_service_eligibility.py
│   ├── test_guardrails.py
│   ├── test_leave.py                   # Leave REST proxy
│   ├── test_leave_chat_tool.py         # Leave chat tool flow
│   ├── test_conversation_context.py    # History context trong triage
│   ├── test_history_bug.py
│   └── …                              # test_auth, test_conversations, test_health…
│
└── requirements.txt                    # fastapi, langgraph, langchain-*, openai, asyncpg, nats-py…
```

**Kiến trúc phân lớp:** Clean Architecture — `domain` không biết `infrastructure`, `application` chỉ phụ thuộc interface (`ports.py`), `infrastructure` implement interface, `interfaces/api` gọi use-case. Dependency injection qua FastAPI `Depends`.

---

## 3. Luồng xử lý chính

### 3.1 Đường LangGraph (canonical — production)

Khi `USE_LANGGRAPH=true` và có OpenAI API key, đây là đường chính.

#### Toàn cảnh graph

```
                          ┌──────────────────────────────────────────────────────┐
                          │ HTTP POST /query                                      │
                          │  ├─ AuthService.authenticate()  ← Bearer token       │
                          │  ├─ RateLimiter.allow()         ← 4 lớp kiểm tra    │
                          │  └─ InputGuardrail.scan()       ← chặn injection     │
                          └─────────────────────┬────────────────────────────────┘
                                                │
                          ┌─────────────────────▼────────────────────────────────┐
                          │ QueryOrchestrationUseCase.stream()                   │
                          │  ├─ DocumentAccessRepo.get_allowed_doc_ids()         │
                          │  ├─ ConversationRepo.get_context()  (N lượt gần)    │
                          │  └─ create_initial_state()  → AgentState             │
                          └─────────────────────┬────────────────────────────────┘
                                                │ graph.astream_events()
                                                │
                                          ┌─────▼──────┐
                                          │ route_entry │  (conditional entry point)
                                          └──┬──────┬──┘
                               shortcut?     │      │ không khớp shortcut
                               ┌─────────────┘      └──────────────┐
                          ┌────▼────┐                         ┌─────▼──────┐
                          │shortcut │                         │  triage    │  LLM call #1
                          │ _node   │  deterministic, ~0ms    │  _node     │  (no tools)
                          └────┬────┘                         └──────┬─────┘
                               │                          route_after_triage
                               │                       ┌──────┴───────┐
                               │               answer? │              │ ALLOW?
                               │           ┌───────────┘              └──────────────┐
                               │      ┌────▼─────┐                            ┌──────▼─────┐
                               └─────►│ answer   │◄──────── answer? ──────────│  think     │ LLM call #2+
                                      │ _node    │      route_after_think      │  _node     │ (bind_tools)
                                      └────┬─────┘                            └──────┬─────┘
                                           │                                  act?   │
                                          END                       ┌─────────────────┘
                                                               ┌────▼────┐
                                                               │  act    │  tool execution
                                                               │  _node  │  (ACL guard)
                                                               └────┬────┘
                                                         route_after_act
                                                       ┌──────┴───────┐
                                               answer? │              │ observe?
                                         (hard-stop)        ┌─────────▼──────┐
                                                            │    observe     │  increment iteration
                                                            │    _node       │  check cap
                                                            └────┬───────────┘
                                                                 │ (always)
                                                                 └──────► think_node
```

Sau khi graph emit `DONE`:
- `OutputGuardrail.redact()` — xoá PII khỏi câu trả lời
- `ConversationRepo.save()` — lưu assistant message kèm sources, latency_ms
- SSE stream token events rồi done event về client

---

#### AgentState — trái tim của graph

`AgentState` là một `TypedDict` được LangGraph quản lý xuyên suốt mọi node. Mỗi node nhận toàn bộ state và trả về **dict partial** để merge vào state (không ghi đè toàn bộ).

```python
class AgentPhase(str, Enum):
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    GENERATING = "generating"   # token đang stream
    DONE = "done"

class AgentState(TypedDict):
    # Conversation (LangGraph tự append qua add_messages, không thay thế)
    messages: Annotated[list, add_messages]

    # Loop control
    iteration: int                           # đang ở lượt thứ mấy (0-based)
    max_iterations: int                      # giới hạn cứng (default 3)

    # Phase tracking (cho SSE streaming)
    phase: AgentPhase
    previous_phase: AgentPhase

    # ReAct scratch pad
    shortcut_response: str | None
    shortcut_outcome: str | None             # "SUCCESS" / "OFF_TOPIC" / "CLARIFY" / "REFUSE" / "NO_INFO"
    tool_results: list[ToolCallResult]
    sources: list[SourceDoc]                 # tài liệu nguồn từ rag_search (score >= threshold)

    # ACL context (inject từ auth + DB tại entry — LLM không thể đọc/sửa)
    user_id: str
    user_role: str
    user_department: str
    allowed_doc_ids: list[str]
    rag_score_threshold: float               # config-driven (default 0.75)
    rag_top_k: int                           # số chunk tối đa mỗi lần gọi (config default 8)

    # Loop termination guards
    force_answer: bool                       # True → think_node emit text answer, không gọi tool
    tool_call_signatures: list[str]          # track (tool, args) đã gọi → chống lặp vô tận

    # Citation
    source_ref_counter: int                  # [N] toàn cục mỗi turn, tăng theo mỗi rag_search call

    # Observability accumulator
    rag_search_events: list                  # JSON-safe dicts mỗi rag_search, consumed bởi LangfuseTracer

    # Metadata
    session_id: str
    question: str
```

**SourceDoc** gồm các trường: `document_name`, `caption`, `heading_path`, `score`, `source_gcs_uri`, `document_id`, `page_number`, `ref` (citation [N]), `chunk_id` (dedup across iterations).

---

#### `route_entry` — quyết định trước khi vào graph

Đây là **conditional entry point** (edge function, không phải node): được gọi ngay khi graph nhận state ban đầu.

```python
def route_entry(state: AgentState) -> str:
    if classify_shortcut(state["question"]) is not None:
        return "shortcut"
    return "triage"
```

`classify_shortcut()` duyệt qua 9 tập phrase theo thứ tự ưu tiên (từ `shortcuts.py`):

| Ưu tiên | Loại | Ví dụ trigger | Response | Outcome |
|---------|------|---------------|----------|---------|
| 1 | emergency | "cháy rồi", "khẩn cấp", "tai nạn", "điện giật" | Hotline 114/115 | SUCCESS |
| 2 | injury | "gãy chân", "bỏng nặng", "ngất xỉu" | Hướng dẫn cấp cứu + nghỉ ốm | SUCCESS |
| 3 | distress | "không muốn sống", "trầm cảm", "tuyệt vọng" | Hỗ trợ tâm lý | SUCCESS |
| 4 | identity | "bạn là ai", "bạn làm được gì" | Giới thiệu chatbot | SUCCESS |
| 5 | user_profile | "tôi là ai", "thông tin tài khoản" | Điền từ `user_role/user_department` | SUCCESS |
| 6 | security | "mật khẩu", "api key", "quyền admin", "superuser" | Từ chối | REFUSE |
| 7 | cross_user | "lương nhân viên phòng", "của đồng nghiệp" | Từ chối ACL | REFUSE |
| 8 | off_topic | "thời tiết", "nhà hàng", "mua gì" | Từ chối off-topic (xoay vòng 3 variant) | OFF_TOPIC |
| 9 | clarify | "alo", "hello", "hi", "xin chào" | Yêu cầu làm rõ | CLARIFY |

**Lưu ý:** IT Support (máy tính hỏng, mất wifi…) **không** phải shortcut — câu hỏi IT fall-through đến triage → ALLOW → RAG tìm runbook nội bộ. Câu hỏi về ngôn ngữ/khả năng chatbot ("bạn nói tiếng anh được không?") cũng ALLOW, không shortcut.

Nếu khớp → trả `"shortcut"`, graph đi thẳng vào `shortcut_node`. **Không tốn API call.**

---

#### `shortcut_node` — fast path không LLM

```python
def shortcut_node(state: AgentState) -> dict:
    result = classify_shortcut(question)    # gọi lại để lấy (response, outcome)
    response, outcome = result
    if response == USER_PROFILE_PLACEHOLDER:
        response = f"Bạn đang đăng nhập với vai trò **{role}**, phòng ban **{dept}**."
    return {
        "shortcut_response": response,
        "shortcut_outcome": outcome,
        "phase": AgentPhase.DONE,
    }
```

Node này set `shortcut_response` và `phase=DONE`, sau đó graph đi thẳng đến `answer_node` rồi `END`. Tổng latency: ~1ms.

---

#### `triage_node` — LLM phân loại câu hỏi (LLM call #1)

Chỉ chạy khi `route_entry` trả `"triage"`.

```
Input:  SystemMessage(TRIAGE_SYSTEM_PROMPT)
        + history messages (N lượt gần nhất, từ state["messages"])
        + HumanMessage(question)
Output: JSON {"route": "...", "safety_type": "...", "clarify_question": "...", "reason": "..."}
```

Model được gọi **không có tools** (`model.ainvoke(messages)`) — đây là lượt phân loại thuần túy.

**5 label canonical (allow-first principle):**

| Label | Ý nghĩa | Hành động |
|-------|---------|-----------|
| `ALLOW` | Trong phạm vi hệ thống (thay cho `in_scope`, `it_support`) | Tiếp tục → `think_node` |
| `SAFETY` | An toàn khẩn cấp, thương tích thể chất, sức khỏe tâm thần nghiêm trọng | Set canned answer theo `safety_type` (emergency/injury/distress) → `answer_node` |
| `META` | Câu hỏi về lịch sử hội thoại ("câu trước tôi hỏi gì") | Lấy prior question từ history → `answer_node` |
| `REFUSE` | Chắc chắn ngoài phạm vi (thay cho `off_topic`) | Set `next_offtopic_answer()` → `answer_node` |
| `CLARIFY` | Trong phạm vi nhưng quá mơ hồ, không có topic anchor (LAST RESORT) | Set LLM-generated clarify question → `answer_node` |

**Backward-compat alias map** — nhãn cũ được map sang nhãn mới (phòng trường hợp model LLM cũ trả nhãn cũ):

| Nhãn cũ | → Nhãn mới |
|---------|-----------|
| `emergency` / `injury` / `distress` | → `SAFETY` |
| `in_scope` / `it_support` | → `ALLOW` |
| `off_topic` | → `REFUSE` |
| `meta_conversation` | → `META` |

**Nguyên tắc ALLOW-first:**
- Có topic anchor (nghỉ phép, lương, runbook, DevOps, query-service…) → ALWAYS ALLOW, không CLARIFY
- Lịch sử hội thoại đã rõ ý → ALLOW dù câu hiện tại ngắn
- Nghi ngờ → ALLOW (RAG kiểm tra sau)
- CLARIFY chỉ khi thực sự không có anchor nào và không có context

**Error handling:** JSON parse lỗi hoặc network fail → fallback về `ALLOW` (không bao giờ từ chối nhầm).

`route_after_triage` kiểm tra `state["shortcut_outcome"]`:
- Có giá trị → `"answer"` (kết thúc)
- Không có → `"think"` (tiếp tục)

---

#### `think_node` — LLM quyết định dùng tool (LLM call #2+)

Node trung tâm của vòng lặp ReAct. Được gọi lần đầu sau `triage_node`, và được gọi lại sau mỗi lượt `observe_node`.

**Xây dựng tool list:**

```python
# Ưu tiên tools_loader (auto-discovered từ mcp-service)
if tools_loader is not None:
    tools = await tools_loader.get_acl_tools(user_id, allowed_doc_ids)
else:
    tools = await build_langgraph_tools(mcp_client, allowed_doc_ids, user_id)
```

Tool list gồm:
- `rag_search(top_k)` — `StructuredTool` schema-only stub; **không nhận `query`** (act_node inject `state["question"]` server-side)
- `hr_query()` — `StructuredTool` schema-only stub; **không có tham số** (act_node inject `user_id` server-side, trả full HR profile)
- Tool generic mới — dict schema `{"type":"function","name":...,"parameters":...}` (auto-discovered từ MCP)

**Hai chế độ invoke:**

```
force_answer = False  →  bound_model = model.bind_tools(tools, tool_choice="auto")
                         response = await bound_model.ainvoke(messages)
                         → LLM có thể emit tool_calls HOẶC text answer

force_answer = True   →  response = await model.ainvoke(messages)  [không bind tools]
                         → LLM buộc phải emit text answer tổng hợp từ ToolMessage đã có
```

`tool_choice="auto"` (không ép `"required"`) — tránh trường hợp model gọi write-tool ngay khi chưa đủ args hoặc chặn bước xác nhận với người dùng.

`force_answer=True` được set bởi:
- `observe_node` khi `iteration >= max_iterations`
- `act_node` khi phát hiện tool call trùng lặp (dedup guard)

`route_after_think` quyết định:
- `response.tool_calls` tồn tại → `"act"`
- Không có tool_calls → `"answer"`

---

#### `act_node` — thực thi tool (ACL guard thực sự)

Node thực sự gọi mcp-service. `think_node` chỉ bind schema để LLM biết tool tồn tại — việc thực thi được tách riêng để inject ACL.

```python
# ACL guard: luôn đọc từ state, không từ tool_args
allowed_doc_ids = frozenset(state["allowed_doc_ids"])
user_id = state["user_id"]
```

**Dedup guard** — kiểm tra trước khi gọi:

```python
sig = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
is_duplicate = sig in existing_sigs
if is_duplicate:
    new_state["force_answer"] = True   # vẫn gọi lần này, nhưng không lặp lại
```

**Dispatch theo tool:**

```
tool_name == "rag_search"
    ├─ allowed_doc_ids rỗng → {"error": "No document access"}, hard_stop → answer (NO_INFO)
    └─ gọi mcp_client.rag_search(query=state["question"], document_ids, top_k)
         ├─ qualified = [r for r in results if r.score >= rag_score_threshold]
         │    ├─ qualified > 0  → data = JSON với ref/citation, sources đầy đủ, success=True
         │    ├─ results > 0 nhưng qualified = 0  → data = JSON kết quả (LLM tự đánh giá),
         │    │   new_sources = [] (score thấp: không show citations), success=True (adaptive fallback)
         │    └─ results = 0  → data = {"results": []}, success=False, KHÔNG hard-stop
         │         → flow tiếp tục → observe → think → LLM tổng hợp warm NO_INFO

tool_name == "hr_query"
    └─ mcp_client.call_tool("hr_query", {"user_id": user_id})
         user_id inject từ state, LLM không thể override
         Trả TOÀN BỘ HR profile JSON → LLM tự lọc phần liên quan

tool_name == <generic> (leave_approvals, resolve_date, leave_types, create_leave_request…)
    └─ mcp_client.call_tool(tool_name, {**tool_args, "user_id": user_id})
         → extract: summary > answer > text > json.dumps(raw)
```

**`route_after_act`:** `shortcut_outcome` được set chỉ khi **lỗi kỹ thuật** (ACL violation, circuit open, exception) → đi thẳng `"answer"`. Empty results bình thường → `"observe"` → `think_node` → LLM xử lý.

**Error handling:**
- `MCPCircuitOpenError` → hard_stop với `_RAG_NO_INFO_ANSWER`, `success=False`
- `Exception` khác → hard_stop với thông báo lỗi, `success=False`

---

#### `observe_node` — cập nhật iteration counter

```python
new_iteration = state["iteration"] + 1
result = {"phase": AgentPhase.OBSERVING, "iteration": new_iteration}
if new_iteration >= state["max_iterations"]:
    result["force_answer"] = True   # hard cap: buộc think_node emit text answer
```

Sau `observe_node`, graph **luôn quay về `think_node`** (`add_edge("observe", "think")`).

---

#### `answer_node` — node kết thúc

Terminal node, chỉ log và set `phase=DONE`:

```python
def answer_node(state: AgentState) -> dict:
    return {"phase": AgentPhase.DONE, "previous_phase": state["phase"]}
```

`orchestration.py` đọc kết quả từ state sau khi graph done:
- **Shortcut/triage path:** câu trả lời là `state["shortcut_response"]`
- **Think path:** câu trả lời là `state["messages"][-1].content` (AIMessage cuối)

---

#### Cơ chế kết thúc vòng lặp (4 loại)

| Cơ chế | Trigger | Hành động |
|--------|---------|-----------|
| **LLM tự kết thúc** | `think_node` emit text answer (không có tool_calls) | `route_after_think → "answer"` |
| **Iteration cap** | `observe_node`: `iteration >= max_iterations` | Set `force_answer=True` → think không bind tools → text answer |
| **Dedup guard** | `act_node`: `(tool_name, args)` đã gọi trước đó | Set `force_answer=True` → think không bind tools → text answer |
| **Hard-stop kỹ thuật** | `act_node`: ACL violation / circuit open / exception | Set `shortcut_outcome="NO_INFO"` → `route_after_act → "answer"` |

---

#### SSE events được emit trong luồng LangGraph

`orchestration.py` subscribe `astream_events()` của graph và map các event sang SSE:

| LangGraph event | SSE payload |
|----------------|-------------|
| `on_chat_model_stream` khi `phase == GENERATING` | `{token, phase:"generating", session_id, iterations}` |
| `on_tool_start` (act_node bắt đầu) | `{phase:"acting", tool, tool_args, session_id, iterations}` |
| `on_tool_end` (act_node xong) | `{phase:"observing", tool, tool_result_preview, session_id, iterations}` |
| Graph kết thúc (answer_node done) | `{done:true, outcome, sources, session_id, iterations}` |

`outcome` là int của enum `Outcome` (`auto()` 1-based): REFUSE=1, CLARIFY=2, NO_INFO=3, OFF_TOPIC=4, SUCCESS=5, ERROR=6.

### 3.2 Đường Legacy (deprecated — mock/test)

Khi `USE_LANGGRAPH=false`:

```
POST /query
  └─ QueryOrchestrationUseCase.stream()
       ├─ ConversationRepo.get_context()
       ├─ _choose_route()
       │   └─ QueryRouter.choose_route()
       │       ├─ Shortcut rule matching (không LLM)
       │       └─ HybridIntentClassifier (rule/embedding/LLM)
       │
       ├─ decision.decision == "identity/clarify/off_topic"
       │   → _handle_direct_response()  (static text)
       │
       ├─ decision.decision == "hr_query"
       │   → _handle_hr() hoặc _handle_generic_tool() [nếu tool_routing_mode=native]
       │
       ├─ decision.decision == <generic discovered tool>
       │   → _handle_generic_tool()  → mcp_client.call_tool() → stream summary
       │
       └─ default → _handle_rag()
           ├─ SemanticCache.get()            — cache hit? → stream ngay
           ├─ mcp_client.rag_search()        — gọi MCP
           ├─ ACL post-filter + score filter
           └─ OpenAIStreamingClient.stream_answer() → SSE tokens
```

### 3.3 Semantic Cache

Khi `_handle_rag()` được gọi (legacy path), cache dùng **cosine similarity** trên bag-of-words:
- Cache key: SHA-256 của danh sách document_ids người dùng được phép (namespace cách ly ACL)
- Cache hit nếu similarity ≥ `semantic_cache_threshold` (default **0.90**) và chưa hết TTL (default 3600s)
- Câu trả lời có fallback ("không tìm thấy thông tin") **không** được cache

---

## 4. Kết nối với các service khác

```
                    ┌─────────────────────────────────────────┐
                    │            query-service                │
                    │            :8001                        │
                    └────┬───────────┬──────────┬────────────┘
                         │           │          │
            ┌────────────▼──┐  ┌─────▼────┐  ┌─▼──────────────────┐
            │ user-service  │  │mcp-service│  │   NATS JetStream   │
            │ :8000         │  │ :8003     │  │   (nats://…:4222)  │
            │ GET /auth/me  │  │ /mcp      │  │                    │
            └───────────────┘  └──────────┘  └──────────┬─────────┘
                                                         │ 3 topics:
                                               doc.access (ACL changes)
                                               notify.doc_new (thông báo)
                                               hr.employee_profile.updated

            ┌──────────────────┐   ┌───────────────────┐
            │ ai-router        │   │ PostgreSQL         │
            │ :8010            │   │ (DATABASE_URL)     │
            │ /v1/chat/        │   │ schema: query_svc  │
            │ completions      │   │ conversations      │
            │ (capability-     │   │ messages           │
            │  based routing)  │   │ document_access    │
            └──────────────────┘   │ notifications      │
                                   │ user_access_profile│
            ┌──────────────────┐   └───────────────────┘
            │ OpenAI API       │
            │ Chat Completions │   ┌───────────────────┐
            │ (LLM inference)  │   │ Redis             │
            └──────────────────┘   │ (rate limiter)    │
                                   └───────────────────┘

            ┌──────────────────┐   ┌───────────────────┐
            │ Langfuse         │   │ LangSmith          │
            │ (observability)  │   │ (observability)    │
            └──────────────────┘   └───────────────────┘

            ┌──────────────────┐   ┌───────────────────┐
            │ LLM-as-judge     │   │ hr-service :8004   │
            │ (guardrails)     │   │ (leave requests)  │
            └──────────────────┘   └───────────────────┘
```

### user-service (`:8000`)
- **Khi nào:** `AUTH_MODE=user_service`
- **Gọi gì:** `GET /auth/me` với Bearer token của user, nhận về user profile (id, email, role, department, is_active, account_type)
- **Fallback:** `AUTH_MODE=mock` dùng hard-coded token table; `AUTH_MODE=jwt` decode JWT local

### mcp-service (`:8003`)
- **Gọi qua:** MCP Streamable HTTP protocol (`/mcp` endpoint)
- **Tool list:** `list_tool_specs()` — query-service tự discover tool tại startup (`warmup()`) và per-request
- **Tool execution:** `call_tool(name, arguments)` — generic; `rag_search(query, document_ids, top_k)` — typed; `hr_query(user_id)` — typed (trả full HR profile)
- **Circuit breaker:** pybreaker, mở sau `mcp_circuit_fail_max` lần lỗi, reset sau `mcp_circuit_reset_timeout_seconds` giây
- **Bảo mật:** `X-Internal-Token` header cho mọi request đến mcp-service
- **Mock mode:** `MCP_MODE=mock` dùng `MockMCPClient` với in-memory data

### ai-router (`:8010`)
- **Vai trò:** API gateway cân bằng tải giữa nhiều OpenAI API key + fallback OpenRouter
- **Endpoint:** `POST /v1/chat/completions` — chuẩn OpenAI Chat Completions
- **Capability-based routing:** `model` field trong request = capability name (router chọn model thật); query-service không hardcode model per-call
- **8 capabilities đã xác nhận:** `think`, `triage`, `embed`, `guardrail`, `rerank`, `caption`, `ocr`, `answer`
- **Auth:** `Bearer AIROUTER_INTERNAL_TOKEN` (tách khỏi OPENAI_API_KEY)
- **Kill-switch:** set `OPENAI_BASE_URL=` (rỗng) → bypass router, gọi thẳng OpenAI
- **GATE 2 test:** `test_llm_architecture_enforcement.py` enforce capability set không drift

### hr-service (`:8004`)
- **Gọi qua:** `HRLeaveClient` với `X-Internal-Token` (không expose thẳng browser)
- **Security pattern:** Frontend gọi query-service bằng JWT → query-service lấy `user_id` từ token (không tin client) → gọi hr-service bằng internal token
- **Endpoints proxy:**
  - `POST /leave-requests` — nhân viên tạo đơn nghỉ
  - `POST /leave-requests/{id}/cancel` — nhân viên hủy đơn
  - `GET /leave-requests/pending-approval` — người duyệt xem hàng đợi
  - `POST /leave-requests/{id}/approve` / `/reject` — người duyệt ra quyết định

### NATS JetStream
- **Subscribe 3 topic (JetStream durable consumers):**
  1. `doc.access` — upsert/delete ACL projection (`document_access` table)
  2. `notify.doc_new` — thông báo tài liệu mới đến người dùng có quyền
  3. `hr.employee_profile.updated` — cập nhật profile nhân viên (role, department, account_type)
- **Deduplication:** OrderedDict-based LRU, max 10 000 entries, TTL 86 400s
- **Poison-message:** lỗi vĩnh viễn (sqlstate 42/22/23, payload sai) → forward đến DLQ topic (`<subject>.dlq`) + `term()` thay vì `nak` vô hạn (tránh NAK-storm); lỗi tạm thời → `nak` bình thường
- **At-least-once delivery** qua durable consumer với `max_deliver=6` + backoff exponential

### PostgreSQL
- **asyncpg** connection pool
- **DSN chuẩn hoá:** `Settings.asyncpg_dsn` → `to_asyncpg_dsn()` trong `db/dsn.py` — một nguồn duy nhất, xoá dialect SQLAlchemy (`postgresql+asyncpg://` → `postgresql://`)
- **Schema namespace:** `query_svc`
- **Bảng chính:**

```sql
query_svc.conversations (id UUID, user_id UUID, title, summary, created_at, updated_at)
query_svc.messages (
    id UUID, conversation_id UUID, user_id UUID, role (user|assistant),
    content TEXT, session_id TEXT, sources JSONB, latency_ms INT,
    feedback SMALLINT (-1|0|1), created_at TIMESTAMPTZ
)
query_svc.document_access (
    document_id UUID PRIMARY KEY, classification VARCHAR,
    allowed_departments TEXT[], allowed_user_ids TEXT[], updated_at TIMESTAMPTZ
)
query_svc.notifications (
    id UUID PRIMARY KEY, user_id UUID, event VARCHAR, message TEXT,
    doc_id UUID NULLABLE, is_read BOOLEAN DEFAULT false, created_at TIMESTAMPTZ
)
query_svc.user_access_profile (
    user_id UUID PRIMARY KEY, account_type VARCHAR, department VARCHAR,
    employment_status VARCHAR, updated_at TIMESTAMPTZ
)
```

- **Mock mode:** `DATABASE_URL=None` → dùng in-memory repo (dict)

### Redis
- **Rate limiter:** sliding window, `RATE_LIMITER_MODE=redis`. Fallback: in-memory (không persist giữa restart)
- **Lua scripts:** atomic multi-scope check (`_ALLOW_LUA`) + concurrency acquisition (`_ACQUIRE_LUA`) với stale-slot cleanup (auto-expire sau 300s)
- **Production bắt buộc:** `RATE_LIMITER_MODE=redis` required khi `APP_ENV=production`

### OpenAI API (qua ai-router hoặc direct)
- **Chat Completions API** — chuẩn portable, không dùng Responses API (OpenAI-only) nữa
- **Adapter canonical:** `OpenAIChatModel` (`langchain_chat_adapter.py`) — `BaseChatModel` wrapper tương thích LangGraph `bind_tools()`
- **Adapter legacy:** `OpenAIResponsesChatModel` (`langchain_responses_adapter.py`) — giữ làm kill-switch, không route qua ai-router
- **Default model:** `gpt-5.4-nano` (`openai_llm_model`), embedding: `text-embedding-3-small`
- **Khi route qua ai-router:** `model` field = capability name (e.g. `"think"`, `"triage"`); router chọn model thật

### Observability (Langfuse + LangSmith)
- **Composite tracer:** fan-out sang nhiều backend đồng thời (`OBSERVABILITY_MODE="langfuse,langsmith"`)
- **Cost calculation:** đọc `model_prices.json` (OpenRouter dataset bundled tại build) qua `ModelPriceCatalog`; optional override path cho hot-update
- **Spans:** per-node LLM generation (triage, think…) + tool span (rag_search với query/top_k/qualified/scores/doc_names/latency) + router metadata (key_id, tier, provider từ `response_metadata["router"]`)
- **Failure isolation:** lỗi từng backend không ảnh hưởng query chính

### Guardrails
- **Input:** phát hiện prompt injection trước khi chạm LLM (chat.completions với capability `"guardrail"`)
- **Output:** redact PII (email, CCCD 12 số, số điện thoại VN) khỏi câu trả lời cuối
- **Fail-open:** lỗi guardrail không block request

---

## 5. Cơ chế bảo vệ (Security & Resilience)

### ACL (Access Control List)
- `DocumentAccessRepo.get_allowed_doc_ids(user_id, role, department, account_type)` — mỗi request fetch danh sách tài liệu cho phép từ DB
- `document_ids` được inject **server-side** vào MCP call, LLM không bao giờ nhìn thấy hoặc override được
- `user_id` inject tương tự vào `hr_query` — người dùng chỉ xem được dữ liệu HR của chính mình
- **Reserved params** (`user_id`, `document_ids`, `top_k`) bị strip khỏi tool schema trước khi gửi cho LLM

### Rate Limiting (4 lớp)
- **Per-user:** N req/phút/user_id (configurable `QUERY_RATE_LIMIT_PER_MINUTE`, default 20)
- **Per-IP:** M req/phút/IP (default 60) — chặn multi-account từ cùng IP
- **Global:** G req/phút toàn service (default 600) — overload protection
- **Concurrency:** tối đa C SSE stream song song/user (default 3)
- Sliding window, cả 4 scope được kiểm tra atomically; fail nếu **bất kỳ** scope nào vượt limit

### Circuit Breaker
- pybreaker tự động ngắt kết nối mcp-service khi liên tục lỗi
- State: closed → open (sau N lỗi) → half-open → closed (sau timeout)
- Khi circuit open: request trả error ngay (không hang); health endpoint báo `mcp_circuit: open`

### LLM Architectural Gates (3 GATE, CI enforcement)
**Mục đích:** đảm bảo mọi LLM/embedding call đều đi qua adapter route-aware (ai-router), tránh bypass gây mất cân bằng key và observability.

- **GATE 1:** chỉ 6 file trong allowlist được gọi OpenAI SDK trực tiếp (`.responses`/`.chat.completions`/`.embeddings.create`). File khác gọi → CI đỏ
- **GATE 1b:** các file trong allowlist PHẢI đọc `base_url` hoặc dùng `build_routed_openai()` — tránh tái diễn bug `AsyncOpenAI()` không base_url bị SDK tự đọc env → gọi `/v1/responses` (router không có) → 404 âm thầm
- **GATE 2:** capability settings (`llm_capability`, `intent_capability`, `guardrail_capability`) PHẢI nằm trong tập hợp 8 capabilities hợp lệ
- **GATE 3:** mọi `BaseChatModel` adapter PHẢI có đủ surface (`bind_tools`, `with_structured_output`, `_astream`, `_should_stream`, `_agenerate`, `invoke`)

File test: `tests/test_llm_architecture_enforcement.py`, `tests/test_chat_adapter_contract.py`

### Shortcut node (zero API cost)
- `classify_shortcut()` kiểm tra **deterministic rules** TRƯỚC bất kỳ LLM call nào
- 9 loại shortcut, ưu tiên từ safety-critical (emergency/injury/distress) đến UX (identity/clarify)
- Tiết kiệm ~1 API call cho phần lớn câu hỏi thông thường

### Dedup guard (LangGraph loop)
- `act_node` track signature `(tool_name, args)` đã thực thi
- Phát hiện duplicate → set `force_answer=True` → `think_node` emit final text answer, không loop thêm
- `observe_node` set `force_answer=True` khi đạt `max_iterations` (default 3)

### Adaptive RAG fallback
- Kết quả ≥ threshold: citations đầy đủ, sources ghi vào state
- Kết quả < threshold nhưng > 0: pass cho LLM context (không show citations) — LLM tự đánh giá
- Kết quả = 0: `{"results": []}` — flow tiếp tục, LLM tổng hợp warm NO_INFO theo AGENT_SYSTEM_PROMPT
- Chỉ hard-stop khi lỗi kỹ thuật (ACL violation, circuit open, exception)

### Semantic cache namespace
- Cache key = SHA-256 của sorted document_ids → người dùng khác ACL không share cache nhầm

### Leave proxy security
- query-service không tin `user_id` từ client; luôn lấy từ JWT decode
- hr-service chỉ nhận internal token, không expose thẳng browser

### DSN chuẩn hoá
- `to_asyncpg_dsn()` trong `db/dsn.py` là nguồn duy nhất xử lý DSN
- Ngăn bug dialect +psycopg còn sót làm connection pool fail âm thầm

---

## 6. Các chế độ vận hành (Environment Variables)

| Biến | Giá trị | Default | Ý nghĩa |
|------|---------|---------|---------|
| `AUTH_MODE` | `mock` / `jwt` / `user_service` | `mock` | Xác thực người dùng |
| `MCP_MODE` | `mock` / `real` / `mcp` | `mock` | Kết nối mcp-service hay dùng mock data |
| `LLM_MODE` | `mock` / `openai` | `openai` | Dùng mock client hay OpenAI thật |
| `LLM_MODEL_ADAPTER` | `responses` / `chat` | `responses` | Adapter LangGraph: `chat`=OpenAIChatModel (portable), `responses`=legacy kill-switch |
| `NATS_MODE` | `mock` / `nats` | `mock` | Subscribe NATS hay bỏ qua |
| `USE_LANGGRAPH` | `true` / `false` | `true` | Dùng LangGraph agent hay legacy orchestration |
| `AGENT_MODE` | `guarded` | `guarded` | Chế độ agent |
| `AGENT_MAX_ITERATIONS` | int | `3` | Số lượt think→act tối đa |
| `GUARDRAILS_MODE` | `off` / `llm_api` / `llm_guard` | `off` | Guardrail backend |
| `GUARDRAIL_MODEL` | string | `None` | Model cho LLM-as-judge guardrail (capability: `guardrail`) |
| `OBSERVABILITY_MODE` | `off` / `langfuse` / `langsmith` / combo | `off` | Observability backend(s) |
| `RATE_LIMITER_MODE` | `memory` / `redis` | `memory` | Rate limiter backend |
| `TOOL_ROUTING_MODE` | `legacy` / `native` | `legacy` | hr_query dùng typed method hay generic call_tool |
| `MCP_TOOL_CACHE_TTL_SECONDS` | int | `300` | Cache TTL cho list_tool_specs() (0=off) |
| `APP_ENV` | `development` / `production` | `development` | Production enforce nhiều constraint |
| `OPENAI_LLM_MODEL` | string | `gpt-5.4-nano` | LLM model (khi direct, không qua ai-router) |
| `OPENAI_BASE_URL` | string | `None` | URL ai-router (`http://ai-router:8010/v1`); rỗng = direct OpenAI |
| `AIROUTER_INTERNAL_TOKEN` | string | `None` | Bearer token gửi cho ai-router (tách khỏi OPENAI_API_KEY) |
| `LLM_CAPABILITY` | string | `think` | Capability name gửi cho ai-router khi route LLM chính |
| `INTENT_CAPABILITY` | string | `triage` | Capability name cho intent/triage classification |
| `GUARDRAIL_CAPABILITY` | string | `guardrail` | Capability name cho guardrail LLM-judge |
| `QUERY_RATE_LIMIT_PER_MINUTE` | int | `20` | Giới hạn per-user |
| `QUERY_RATE_LIMIT_PER_IP_PER_MINUTE` | int | `60` | Giới hạn per-IP |
| `QUERY_RATE_LIMIT_GLOBAL_PER_MINUTE` | int | `600` | Giới hạn global |
| `QUERY_MAX_CONCURRENT_PER_USER` | int | `3` | Max concurrent SSE streams/user |
| `RAG_SCORE_THRESHOLD` | float | `0.75` | Ngưỡng điểm min để chunk được show citations |
| `RAG_TOP_K` | int | `8` | Số chunk tối đa mỗi rag_search call |
| `RAG_RESULT_LIMIT` | int | `3` | Số source tối đa trong done event |
| `SEMANTIC_CACHE_THRESHOLD` | float | `0.90` | Ngưỡng cosine similarity cache hit |
| `SEMANTIC_CACHE_TTL_SECONDS` | int | `3600` | Cache TTL (seconds) |
| `MODEL_PRICE_ENABLED` | bool | `true` | Bật cost calculation trong tracer |
| `MODEL_PRICE_PATH` | string | `/app/...` | Path đến model_prices.json |
| `HR_SERVICE_URL` | string | `http://localhost:8004` | URL hr-service |
| `QDRANT_URL` | string | `http://localhost:6333` | URL Qdrant (vector store) |
| `LANGSMITH_API_KEY` | string | `None` | LangSmith API key |

**Chế độ development (tất cả mock, offline):**
```
AUTH_MODE=mock MCP_MODE=mock LLM_MODE=mock NATS_MODE=mock USE_LANGGRAPH=false
```

**Chế độ production:**
```
APP_ENV=production AUTH_MODE=jwt MCP_MODE=real LLM_MODE=openai NATS_MODE=nats
USE_LANGGRAPH=true LLM_MODEL_ADAPTER=chat GUARDRAILS_MODE=llm_api OBSERVABILITY_MODE=langfuse
RATE_LIMITER_MODE=redis OPENAI_BASE_URL=http://ai-router:8010/v1
AIROUTER_INTERNAL_TOKEN=<token> LLM_CAPABILITY=think INTENT_CAPABILITY=triage
```

Validator tại startup (`Settings.validate_runtime_config`) fail fast nếu thiếu (mock modes bị cấm, JWT_SECRET_KEY phải ≥ 32 ký tự, không phải giá trị default).

---

## 7. Dynamic Tool Discovery

Query-service **tự động phát hiện tool mới** từ mcp-service mà không cần sửa code routing:

1. **Startup:** `LangChainMCPToolsLoader.warmup()` gọi `list_tool_specs()` từ mcp-service, log tool list
2. **Per-request (`think_node`):** `get_acl_tools()` gọi lại `list_tool_specs()`, build tool schema động:
   - `rag_search` → `StructuredTool` bespoke (schema-only stub, không có `query` param; act_node inject `state["question"]`)
   - `hr_query` → `StructuredTool` bespoke (schema-only stub, không có tham số; act_node inject `user_id`, trả full profile)
   - Tool mới bất kỳ → `{"type":"function", "name":…, "parameters":…}` dict (generic, auto-discovered)
3. **`act_node`:** `rag_search/hr_query` giữ xử lý riêng; tool khác → `mcp_client.call_tool()` + stream `summary`
4. **Mock:** `MockMCPClient.register_tool(spec, response)` — test thêm tool thứ 3, không sửa routing

**Để thêm tool summary-style vào production:**
1. Implement tool mới trong mcp-service (trả về `{"summary": "..."}`)
2. Deploy mcp-service
3. query-service tự discover tại next request — **0 dòng code thay đổi**

---

## 8. API Endpoints

| Method | Path | Mô tả |
|--------|------|-------|
| `POST` | `/query` | Gửi câu hỏi → SSE stream (token events + done event) |
| `GET` | `/conversations` | Danh sách hội thoại (paginated) |
| `GET` | `/conversations/{id}` | Chi tiết hội thoại + messages |
| `PATCH` | `/conversations/{id}` | Đổi tên hội thoại |
| `DELETE` | `/conversations/{id}` | Xóa một hội thoại |
| `DELETE` | `/conversations` | Xóa toàn bộ lịch sử user |
| `GET` | `/notifications` | SSE stream thông báo real-time |
| `GET` | `/notifications/history` | Lịch sử thông báo (paginated, optional unread_only) |
| `GET` | `/notifications/unread-count` | Đếm thông báo chưa đọc |
| `POST` | `/notifications/{id}/read` | Đánh dấu đã đọc |
| `POST` | `/feedback` | Gửi feedback (-1/1) cho câu trả lời |
| `POST` | `/leave-requests` | Tạo đơn nghỉ phép |
| `POST` | `/leave-requests/{id}/cancel` | Hủy đơn nghỉ |
| `GET` | `/leave-requests/pending-approval` | Hàng đợi đơn chờ duyệt (approver) |
| `POST` | `/leave-requests/{id}/approve` | Duyệt đơn |
| `POST` | `/leave-requests/{id}/reject` | Từ chối đơn |
| `GET` | `/health` | Health check (db, redis, mcp, nats, circuit) |
| `GET` | `/admin/metrics` | Metrics: daily queries, top questions, feedback rate |
| `GET/POST` | `/admin/*` | Admin endpoints (chỉ khi `ENABLE_DEV_ENDPOINTS=true`) |

**Format SSE (`POST /query`):**

```
data: {"token": "Bạn còn ", "phase": "generating", "session_id": "...", "iterations": 1}
data: {"token": "12 ngày nghỉ", "phase": "generating", ...}
data: {"phase": "acting", "tool": "hr_query", "tool_args": {}, ...}
data: {"phase": "observing", "tool": "hr_query", "tool_result_preview": "...", ...}
data: {"done": true, "outcome": 5, "sources": [...], "session_id": "...", "iterations": 2}
```

`outcome` (int, 1-based `auto()`): REFUSE=1, CLARIFY=2, NO_INFO=3, OFF_TOPIC=4, SUCCESS=5, ERROR=6.

---

## 9. Tại sao thiết kế như vậy?

### LangGraph thay vì ReAct text loop
LangGraph quản lý state machine rõ ràng (shortcut → triage → think → act → observe → answer). Mỗi node có trách nhiệm độc lập, dễ test riêng. Không phụ thuộc vào LLM parse THOUGHT/ACTION text — dùng native `tool_calls`.

### Chat Completions thay vì Responses API
Responses API là OpenAI-only, không route qua ai-router (chỉ proxy `/v1/chat/completions`). `OpenAIChatModel` dùng Chat Completions chuẩn → chạy được với mọi OpenAI-compatible provider (ai-router, OpenRouter, vLLM…). `langchain_responses_adapter.py` giữ làm kill-switch.

### Capability-based routing qua ai-router
Thay vì hardcode model name per-call, query-service gửi capability name (`"think"`, `"triage"`, `"guardrail"`…). ai-router chọn model thật và cân bằng key → query-service không cần biết model thật, routing policy nằm ở ai-router.

### Tách shortcut_node khỏi triage_node
- Shortcut (emergency/security/identity): deterministic rule matching, **không gọi API**, độ trễ ~1ms
- Triage: LLM call, dùng khi câu hỏi cần ngữ cảnh để phân loại (ALLOW/REFUSE/CLARIFY/SAFETY/META)

### Triage 5 label thay vì 8 route
Gộp emergency/injury/distress → SAFETY (có sub-field `safety_type`). Gộp in_scope/it_support → ALLOW. Đơn giản hoá routing logic, backward-compat alias map giữ cho model cũ vẫn route đúng.

### hr_query không có `intent` param
Model cũ hay gọi `hr_query(intent="")` rỗng → hr-service 422. Nay `hr_query()` không tham số, trả full profile JSON, LLM tự lọc phần liên quan → loại bỏ hoàn toàn failure mode "intent rỗng".

### rag_search không có `query` param
`query` inject server-side từ `state["question"]` — ngăn prompt injection qua tool args, và đảm bảo query luôn là câu hỏi gốc của user, không phải text LLM tự compose.

### Adaptive RAG fallback (3 mức)
Thay vì hard-stop khi empty results, act_node phân biệt 3 trường hợp: (1) qualified → citations đầy đủ; (2) below-threshold → context cho LLM không có citations; (3) empty → LLM tổng hợp warm NO_INFO. Hard-stop chỉ cho lỗi kỹ thuật thực sự.

### `route_after_act` — short-circuit khi lỗi kỹ thuật
Thay vì để vòng lặp think→act→observe tiếp tục vô ích khi ACL violation hay circuit open, `act_node` set `shortcut_outcome="NO_INFO"` ngay và `route_after_act` bỏ qua observe. Tiết kiệm 1 LLM call.

### ACL inject server-side, không tin LLM
LLM biết **tên tool** và **args cần**, nhưng không bao giờ biết `document_ids` hay `user_id` thực sự. Hai giá trị này inject tại `act_node` từ `state`. Ngay cả prompt injection cũng không thể vượt qua.

### Architectural gate tests (3 GATE)
Enforce tại CI: không thể thêm file gọi thẳng SDK (GATE 1), client phải route-aware (GATE 1b), capability phải hợp lệ (GATE 2), adapter phải đủ surface (GATE 3). Vi phạm = CI đỏ = không lên prod.

### Citation ref counter toàn cục
`source_ref_counter` tăng theo mỗi rag_search call, không theo chunk. Kết quả: mỗi chunk trong toàn bộ session có citation `[N]` duy nhất, dù gọi rag_search bao nhiêu lần. Dedup bằng `chunk_id`.

### Rate limiting 4 lớp
Per-user ngăn spam từ một tài khoản. Per-IP ngăn multi-account từ cùng IP. Global ngăn overload toàn service. Concurrency cap ngăn một user chiếm hết connection pool SSE.

### Semantic cache với namespace ACL
Nếu Alice và Bob có quyền xem tài liệu khác nhau, cache của họ được namespace riêng (hash của doc_ids). Câu hỏi giống nhau nhưng ACL khác → không share cache.

### Composite tracer (Langfuse + LangSmith)
Cost calculation thực hiện local (không phụ thuộc pricing API của Langfuse self-host v2). Fan-out tracer đảm bảo lỗi từng backend không ảnh hưởng query chính. Router metadata (`key_id`, `tier`, `provider`) từ `response_metadata["router"]` cho phép drill-down per-key trong Langfuse.

### Leave proxy trong query-service
hr-service không xác thực user (chỉ nhận internal token), không được expose thẳng browser. query-service đứng làm proxy: xác thực JWT, lấy user_id từ token, rồi mới gọi hr-service với internal token.

### Leave confirmation flow (chat → UI form)
User không tạo đơn nghỉ trực tiếp qua chat. Thay vào đó, LLM resolve các field cần thiết, emit JSON `{"action_type":"create_leave_request","items":[...]}`, UI render form xác nhận. Tránh submit nhầm, tránh LLM tự add ngày sai.

### DSN chuẩn hoá tập trung
`to_asyncpg_dsn()` là nguồn duy nhất xử lý cắt dialect — ngăn bug khi dùng `postgresql+asyncpg://` (SQLAlchemy-style) với asyncpg (cần `postgresql://`).

### NATS poison-message DLQ
Message lỗi vĩnh viễn không còn bị `nak` vô hạn (NAK-storm). Thay vào đó: `term()` + forward đến DLQ topic cho ops xem xét sau. `max_deliver=6` + backoff là backstop cuối cùng.

### Dynamic tool discovery
Tool list được build dynamically mỗi request từ `list_tool_specs()`. Bất kỳ tool nào mcp-service khai báo đều tự động bind vào model — không cần release query-service.

---

## 10. Chạy local

```bash
cd src/query-service

# Development (all mock, no external services needed)
cp .env.example .env
MCP_MODE=mock LLM_MODE=mock AUTH_MODE=mock USE_LANGGRAPH=false \
  uvicorn app.interfaces.api.main:app --port 8001 --reload

# Test suite
.venv/Scripts/python.exe -m pytest tests/ -q
```

**Test nhanh qua PowerShell:**
```powershell
$body = @{ question = "Chính sách nghỉ phép là gì?"; user_id = "11111111-1111-4111-8111-111111111111" } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8001/query -Method Post `
  -Headers @{ Authorization = "Bearer mock-user-hr" } `
  -ContentType "application/json" -Body $body
```
