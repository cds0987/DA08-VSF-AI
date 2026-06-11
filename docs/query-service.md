# Query Service — Tài liệu kỹ thuật

> Cập nhật: 2026-06-10 | Branch: `dungpq/query-service`

---

## 1. Query Service là gì?

Query Service là **cửa vào duy nhất** cho mọi câu hỏi của người dùng cuối trong hệ thống VinSmartFuture RAG Chatbot. Nó đóng vai trò **orchestrator** — nhận câu hỏi từ frontend qua HTTP, phân loại, chọn tool phù hợp, gọi backend (mcp-service), sau đó stream câu trả lời về dạng **Server-Sent Events (SSE)**.

**Nhiệm vụ cốt lõi:**
- Xác thực người dùng và kiểm tra rate limit
- Phân loại câu hỏi (triage): shortcut, off-topic, HR, tài liệu nội bộ
- Thực hiện ACL: chỉ truy vấn tài liệu người dùng được phép xem
- Gọi tool qua MCP protocol (rag_search / hr_query / generic)
- Stream câu trả lời từng token về frontend
- Lưu lịch sử hội thoại, quản lý thông báo

---

## 2. Cấu trúc thư mục

```
src/query-service/
├── app/
│   ├── domain/                         # Lớp nghiệp vụ thuần túy (không phụ thuộc framework)
│   │   ├── entities/
│   │   │   ├── conversation.py         # Entity Conversation, Message
│   │   │   └── notification.py         # Entity Notification
│   │   ├── repositories/               # Interface (Protocol) — định nghĩa contract
│   │   │   ├── conversation_repository.py
│   │   │   ├── document_access_repository.py
│   │   │   ├── notification_repository.py
│   │   │   └── user_access_profile_repository.py
│   │   └── outcome.py                  # Enum Outcome: SUCCESS/NO_INFO/REFUSE/CLARIFY/OFF_TOPIC/ERROR
│   │
│   ├── application/                    # Use-case và orchestration logic
│   │   ├── ports.py                    # Protocol interfaces: MCPToolClient, LLMStreamingClient, SemanticCache…
│   │   ├── tools.py                    # TOOL_DEFINITIONS (OpenAI schema), ACL_WHITELIST
│   │   ├── prompts.py                  # TRIAGE_SYSTEM_PROMPT + AGENT_SYSTEM_PROMPT
│   │   ├── shortcuts.py                # Classify shortcut (emergency/injury/distress/identity/security…)
│   │   ├── route_decision.py           # RouteDecision dataclass + normalize/coerce logic
│   │   ├── tool_decision.py            # ToolDecision dataclass + VALID_TOOL_NAMES
│   │   ├── query_router.py             # QueryRouter — intent classifier → route decision
│   │   ├── intent_classifier.py        # HybridIntentClassifier (rule + embedding + LLM)
│   │   ├── langgraph_state.py          # AgentState TypedDict + create_initial_state()
│   │   ├── langgraph_edges.py          # Conditional edges: route_entry / route_after_triage / route_after_think
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
│   │   │   ├── semantic_cache.py       # InMemorySemanticCache (cosine similarity, TTL)
│   │   │   └── rate_limiter.py         # RateLimiter: in-memory / Redis sliding window
│   │   ├── db/
│   │   │   ├── postgres_conversation_repo.py   # asyncpg, PostgreSQL
│   │   │   ├── postgres_document_access_repo.py
│   │   │   ├── postgres_notification_repo.py
│   │   │   ├── postgres_user_access_profile_repo.py
│   │   │   ├── mock_conversation_repo.py       # In-memory (test/dev)
│   │   │   ├── mock_document_access_repo.py
│   │   │   ├── mock_notification_repo.py
│   │   │   ├── mock_user_access_profile_repo.py
│   │   │   └── mock_data.py            # MOCK_DOCUMENTS, MOCK_HR_DATA
│   │   ├── external/
│   │   │   ├── mcp_client.py           # MockMCPClient + MCPStreamableHttpClient (circuit breaker)
│   │   │   ├── langchain_mcp_client.py # LangChainMCPToolsLoader — dynamic tool discovery
│   │   │   ├── langchain_responses_adapter.py  # OpenAIResponsesChatModel (LangChain ↔ Responses API)
│   │   │   ├── openai_client.py        # OpenAIStreamingClient — stream_answer()
│   │   │   ├── tool_decision_client.py # OpenAIToolDecisionClient + MockToolDecisionClient (deprecated)
│   │   │   └── intent_ai_client.py     # OpenAIIntentLLMClient, TokenHashIntentEmbeddingClient
│   │   ├── guardrails/
│   │   │   └── llm_guard_service.py    # NoOpGuardrail / LlmGuardInputGuardrail / LlmGuardOutputGuardrail
│   │   ├── messaging/
│   │   │   ├── nats_events.py          # Event schemas + QueryNatsEventHandler
│   │   │   ├── nats_subscriber.py      # NatsSubscriberManager (subscribe 3 topic)
│   │   │   └── notification_service.py # NotificationService
│   │   ├── observability/
│   │   │   └── langfuse_tracing.py     # build_langfuse_callback()
│   │   └── sse/
│   │       └── connection_manager.py   # SSE connection manager
│   │
│   └── interfaces/api/                 # HTTP layer (FastAPI)
│       ├── main.py                     # App entry, lifespan, CORS, health check
│       ├── dependencies.py             # Dependency injection (lru_cache singletons)
│       ├── routers/
│       │   ├── query.py                # POST /query → SSE stream
│       │   ├── conversations.py        # GET/DELETE /conversations
│       │   ├── notifications.py        # GET/PATCH /notifications
│       │   ├── feedback.py             # POST /feedback
│       │   └── admin.py                # Admin endpoints (dev only)
│       ├── schemas/                    # Pydantic request/response schemas
│       └── sse.py                      # format_sse() helper
│
├── tests/                              # pytest (asyncio, ASGI transport)
│   ├── conftest.py                     # Fixtures, mock tokens, parse_sse()
│   ├── test_query.py                   # SSE stream shape, validation
│   ├── test_acl.py                     # ACL enforcement
│   ├── test_tool_discovery.py          # Dynamic tool discovery (Issue #43)
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
                          │  ├─ RateLimiter.allow()         ← 20 req/phút/user  │
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
                                          │ route_entry │  (edge function, không phải node)
                                          └──┬──────┬──┘
                               shortcut?     │      │ không khớp shortcut
                               ┌─────────────┘      └──────────────┐
                          ┌────▼────┐                         ┌─────▼──────┐
                          │shortcut │                         │  triage    │  LLM call #1
                          │ _node   │  deterministic, ~0ms    │  _node     │  (no tools)
                          └────┬────┘                         └──────┬─────┘
                               │                          route_after_triage
                               │                       ┌──────┴───────┐
                               │               answer? │              │ in_scope?
                               │           ┌───────────┘              └──────────────┐
                               │      ┌────▼─────┐                            ┌──────▼─────┐
                               └─────►│ answer   │◄──────── answer? ──────────│  think     │ LLM call #2
                                      │ _node    │      route_after_think      │  _node     │ (bind_tools)
                                      └────┬─────┘                            └──────┬─────┘
                                           │                                  act?   │
                                          END                       ┌─────────────────┘
                                                               ┌────▼────┐
                                                               │  act    │  tool execution
                                                               │  _node  │  (ACL guard)
                                                               └────┬────┘
                                                                    │ (always)
                                                               ┌────▼────┐
                                                               │ observe │  increment iteration
                                                               │ _node   │  check cap
                                                               └────┬────┘
                                                                    │ (always loop back)
                                                                    └──────► think_node
```

Sau khi graph emit `DONE`:
- `OutputGuardrail.redact()` — xoá PII khỏi câu trả lời
- `ConversationRepo.save()` — lưu assistant message
- SSE stream token events rồi done event về client

---

#### AgentState — trái tim của graph

`AgentState` là một `TypedDict` được LangGraph quản lý xuyên suốt mọi node. Mỗi node nhận toàn bộ state và trả về **dict partial** để merge vào state (không ghi đè toàn bộ).

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # LangGraph tự append, không thay thế
    iteration: int                           # đang ở lượt thứ mấy (0-based)
    max_iterations: int                      # giới hạn cứng (default 3)
    phase: AgentPhase                        # THINKING / ACTING / OBSERVING / DONE
    previous_phase: AgentPhase

    shortcut_response: str | None            # câu trả lời canned (shortcut/triage path)
    shortcut_outcome: str | None             # "SUCCESS" / "OFF_TOPIC" / "CLARIFY"
    tool_results: list[ToolCallResult]       # tất cả lần gọi tool trong session này
    sources: list[SourceDoc]                 # tài liệu nguồn từ rag_search

    user_id: str                             # từ auth, LLM không thể đọc/sửa
    user_role: str
    user_department: str
    allowed_doc_ids: list[str]               # từ DB, LLM không biết giá trị này

    force_answer: bool                       # True → think_node bắt buộc emit text answer
    tool_call_signatures: list[str]          # track (tool, args) đã gọi → chống lặp vô tận

    session_id: str
    question: str
```

Hai trường `user_id` và `allowed_doc_ids` được inject từ auth + DB tại `create_initial_state()` và **không bao giờ được ghi lại từ LLM**. Đây là lớp ACL cứng ở tầng state.

---

#### `route_entry` — quyết định trước khi vào graph

Đây là **conditional entry point** (edge function, không phải node): được gọi ngay khi graph nhận state ban đầu.

```python
def route_entry(state: AgentState) -> str:
    if classify_shortcut(state["question"]) is not None:
        return "shortcut"
    return "triage"
```

`classify_shortcut()` duyệt qua các tập phrase theo thứ tự ưu tiên:

| Ưu tiên | Loại | Ví dụ trigger | Response |
|---------|------|---------------|----------|
| 1 | emergency | "cháy", "khẩn cấp", "nguy hiểm" | Hotline khẩn cấp |
| 2 | injury | "tai nạn lao động", "bị thương" | Hướng dẫn sơ cứu |
| 3 | distress | "stress nặng", "kiệt sức", "muốn nghỉ việc" | Hỗ trợ tâm lý |
| 4 | identity | "bạn là ai", "tên bạn là gì" | Giới thiệu chatbot |
| 5 | user_profile | "tôi là ai", "role của tôi" | Điền từ `user_role/user_department` |
| 6 | security | "hack", "bypass", "admin password" | Từ chối |
| 7 | cross_user | "lương của Nguyễn Văn A", "thông tin người khác" | Từ chối ACL |
| 8 | it_support | "máy tính hỏng", "reset password" | Hướng IT support |
| 9 | off_topic | "thời tiết", "bóng đá", câu ngoài phạm vi | Từ chối off-topic |
| 10 | clarify | câu quá ngắn/mơ hồ | Yêu cầu làm rõ |

Nếu khớp → trả `"shortcut"`, graph đi thẳng vào `shortcut_node`. **Không tốn API call.**

---

#### `shortcut_node` — fast path không LLM

```python
def shortcut_node(state: AgentState) -> dict:
    result = classify_shortcut(question)   # gọi lại, lần này để lấy (response, outcome)
    response, outcome = result
    if response == USER_PROFILE_PLACEHOLDER:
        response = f"Bạn đang đăng nhập với vai trò {role}, phòng ban {dept}."
    return {
        "shortcut_response": response,
        "shortcut_outcome": outcome,  # "SUCCESS" hoặc "OFF_TOPIC"
        "phase": AgentPhase.DONE,
    }
```

Node này set `shortcut_response` và `phase=DONE`, sau đó graph đi thẳng đến `answer_node` rồi `END`. Tổng latency: ~1ms.

---

#### `triage_node` — LLM phân loại câu hỏi (LLM call #1)

Chỉ chạy khi `route_entry` trả `"triage"` (câu hỏi không khớp shortcut).

```
Input:  SystemMessage(TRIAGE_SYSTEM_PROMPT)
        + history messages (N lượt gần nhất, từ state["messages"])
        + HumanMessage(question)
Output: JSON {"route": "...", "reason": "...", "clarify_question": "..."}
```

Model được gọi **không có tools** (`model.ainvoke(messages)`) — đây là lượt phân loại thuần túy. Không có tool_calls trong response.

**8 route hợp lệ:**

| Route | Hành động |
|-------|-----------|
| `in_scope` | Tiếp tục → `think_node` (gọi tool) |
| `off_topic` | Set `shortcut_response=next_offtopic_answer()`, `shortcut_outcome="OFF_TOPIC"` → `answer_node` |
| `clarify` | Set `shortcut_response=clarify_question`, `shortcut_outcome="CLARIFY"` → `answer_node` |
| `emergency` | Set canned response, `shortcut_outcome="SUCCESS"` → `answer_node` |
| `injury` | nt. |
| `distress` | nt. |
| `it_support` | Set IT_SUPPORT_ANSWER → `answer_node` |
| `meta_conversation` | Tra lịch sử, trả lời "câu hỏi trước của bạn là…" → `answer_node` |

**Error handling:** Nếu JSON parse lỗi hoặc network fail → fallback về `"in_scope"` (không bao giờ từ chối nhầm câu hỏi hợp lệ).

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
- `rag_search` — `StructuredTool` với `_RagSearchInput` (query, top_k), ACL doc_ids đã inject vào closure
- `hr_query` — `StructuredTool` với `_HrQueryInput` (intent: leave_balance/leave_requests/payroll), user_id đã inject
- Tool generic mới — dict schema `{"type":"function","name":...,"parameters":...}` (auto-discovered)

**Hai chế độ invoke:**

```
force_answer = False  →  bound_model = model.bind_tools(tools, tool_choice="auto")
                         response = await bound_model.ainvoke(messages)
                         → LLM có thể emit tool_calls HOẶC text answer

force_answer = True   →  response = await model.ainvoke(messages)  [không bind tools]
                         → LLM buộc phải emit text answer tổng hợp từ ToolMessage đã có
```

`force_answer=True` được set bởi:
- `observe_node` khi `iteration >= max_iterations`
- `act_node` khi phát hiện tool call trùng lặp (dedup guard)

`route_after_think` sau đó quyết định:
- `response.tool_calls` tồn tại → `"act"`
- Không có tool_calls (text answer) → `"answer"`

---

#### `act_node` — thực thi tool (ACL guard thực sự)

Node này là nơi **thực sự gọi mcp-service**, không phải `think_node`. Lý do: `think_node` chỉ là schema binding để LLM biết tool tồn tại — việc thực thi được tách riêng để inject ACL.

```python
tool_call = last_msg.tool_calls[0]   # lấy tool_call đầu tiên từ AIMessage
tool_name = tool_call["name"]
tool_args = tool_call.get("args", {})

# ACL guard: luôn đọc từ state, không từ tool_args
allowed_doc_ids = frozenset(state["allowed_doc_ids"])
user_id = state["user_id"]
```

**Dedup guard** — kiểm tra trước khi gọi:

```python
sig = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
is_duplicate = sig in existing_sigs
# Vẫn gọi tool lần này, nhưng set force_answer=True để không lặp lại
if is_duplicate:
    new_state["force_answer"] = True
```

**Dispatch theo tool:**

```
tool_name == "rag_search"
    ├─ allowed_doc_ids rỗng → {"error": "No document access"}, success=False
    └─ gọi mcp_client.rag_search(query, document_ids, top_k)
         ├─ qualified = [r for r in results if r.score >= 0.70]
         │   (chunk score thấp → LLM hallucinate, lọc luôn)
         ├─ sources = [r for r in qualified if r.score >= 0.75]
         │   (nguồn trích dẫn ngưỡng cao hơn)
         └─ success = bool(qualified)

tool_name == "hr_query"
    └─ mcp_client.hr_query(user_id=user_id, intent=...)
         user_id inject từ state, LLM không thể override
         → returns result.summary  (string)

tool_name == <generic>
    └─ mcp_client.call_tool(tool_name, {**tool_args, "user_id": user_id})
         → raw dict, extract: summary > answer > text > json.dumps(raw)
         success = bool(summary and summary not in ("{}", "null", ""))
```

**Error handling trong act_node:**
- `MCPCircuitOpenError` → log warning, trả error message, `success=False` (circuit breaker đang open)
- `Exception` khác → log error, trả thông báo lỗi tiếng Việt, `success=False`

Kết quả được bọc trong `ToolMessage` và append vào `state["messages"]` để `think_node` lần sau đọc được.

---

#### `observe_node` — cập nhật iteration counter

Node đơn giản nhất, nhưng đảm nhận hai việc quan trọng:

```python
new_iteration = state["iteration"] + 1
result = {
    "phase": AgentPhase.OBSERVING,
    "iteration": new_iteration,
}
if new_iteration >= state["max_iterations"]:
    result["force_answer"] = True   # hard cap: buộc think_node emit text answer
```

Sau `observe_node`, graph **luôn quay về `think_node`** (`add_edge("observe", "think")`). `think_node` sẽ quyết định tiếp tục hay kết thúc dựa vào `force_answer`.

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

#### Vòng lặp ReAct — ví dụ cụ thể

Câu hỏi: *"Tôi còn bao nhiêu ngày nghỉ và chính sách nghỉ phép là gì?"*

```
iteration=0
  think_node:   LLM thấy 2 tool → emit tool_call: hr_query(intent="leave_balance")
  act_node:     gọi mcp_client.hr_query(user_id="u1", intent="leave_balance")
                → "Bạn còn 12 ngày phép năm"
                → ToolMessage appended
  observe_node: iteration → 1, chưa đạt max (3), force_answer=False

iteration=1
  think_node:   LLM thấy ToolMessage trước + tool list → emit tool_call: rag_search(query="chính sách nghỉ phép")
  act_node:     gọi mcp_client.rag_search(query="...", document_ids=["doc1","doc2"], top_k=5)
                → 3 chunk score ≥ 0.70, sources ghi lại
                → ToolMessage appended
  observe_node: iteration → 2, chưa đạt max, force_answer=False

iteration=2
  think_node:   LLM thấy đủ context → emit text answer (không có tool_calls)
  route_after_think: không có tool_calls → "answer"
  answer_node:  phase=DONE

Kết quả: câu trả lời tổng hợp từ cả HR data + tài liệu, kèm sources từ rag_search
```

---

#### Cơ chế kết thúc vòng lặp (3 loại)

| Cơ chế | Trigger | Hành động |
|--------|---------|-----------|
| **LLM tự kết thúc** | `think_node` emit text answer (không có tool_calls) | `route_after_think → "answer"` |
| **Iteration cap** | `observe_node`: `iteration >= max_iterations` | Set `force_answer=True` → think gọi không có tools → text answer |
| **Dedup guard** | `act_node`: `(tool_name, args)` đã gọi trước đó | Set `force_answer=True` → think gọi không có tools → text answer |

---

#### SSE events được emit trong luồng LangGraph

`orchestration.py` subscribe `astream_events()` của graph và map các event sang SSE:

| LangGraph event | SSE payload |
|----------------|-------------|
| `on_chat_model_stream` khi `phase == GENERATING` | `{token, phase:"generating", session_id, iterations}` |
| `on_tool_start` (act_node bắt đầu) | `{phase:"acting", tool, tool_args, session_id, iterations}` |
| `on_tool_end` (act_node xong) | `{phase:"observing", tool, tool_result_preview, session_id, iterations}` |
| Graph kết thúc (answer_node done) | `{done:true, outcome, sources, session_id, iterations}` |

`outcome` là int của enum `Outcome`: SUCCESS=5, NO_INFO=3, REFUSE=1, CLARIFY=2, OFF_TOPIC=4, ERROR=6.

### 3.2 Đường Legacy (deprecated — mock/test)

Khi `USE_LANGGRAPH=false` (test/mock mode):

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

Khi `_handle_rag()` được gọi, cache dùng **cosine similarity** trên bag-of-words:
- Cache key: SHA-256 của danh sách document_ids người dùng được phép (namespace cách ly ACL)
- Cache hit nếu similarity ≥ `semantic_cache_threshold` (default 0.95) và chưa hết TTL
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
            │ OpenAI API       │   │ PostgreSQL         │
            │ Responses API    │   │ (DATABASE_URL)     │
            │ (LLM inference)  │   │ conversations      │
            └──────────────────┘   │ document_access    │
                                   │ notifications      │
            ┌──────────────────┐   │ user_access_profile│
            │ Redis            │   └───────────────────┘
            │ (rate limiter)   │
            └──────────────────┘   ┌───────────────────┐
                                   │ Langfuse           │
            ┌──────────────────┐   │ (observability)   │
            │ llm-guard        │   └───────────────────┘
            │ (guardrails)     │
            └──────────────────┘
```

### user-service (`:8000`)
- **Khi nào:** `AUTH_MODE=user_service`
- **Gọi gì:** `GET /auth/me` với Bearer token của user, nhận về user profile (id, email, role, department)
- **Fallback:** `AUTH_MODE=mock` dùng hard-coded token table; `AUTH_MODE=jwt` decode JWT local

### mcp-service (`:8003`)
- **Gọi qua:** MCP Streamable HTTP protocol (`/mcp` endpoint)
- **Tool list:** `list_tools()` / `list_tool_specs()` — query-service tự discover tool tại startup (`warmup()`) và per-request
- **Tool execution:** `call_tool(name, arguments)` — generic; `rag_search(query, document_ids, top_k)` — typed; `hr_query(user_id, intent)` — typed
- **Circuit breaker:** pybreaker, mở sau `mcp_circuit_fail_max` lần lỗi, reset sau `mcp_circuit_reset_timeout_seconds` giây
- **Bảo mật:** `X-Internal-Token` header cho mọi request đến mcp-service
- **Mock mode:** `MCP_MODE=mock` dùng `MockMCPClient` với in-memory data (test/dev offline)

### NATS JetStream
- **Subscribe 3 topic:**
  1. `doc.access` — cập nhật quyền truy cập tài liệu (upsert/delete `document_access` table)
  2. `notify.doc_new` — thông báo tài liệu mới đến người dùng có quyền
  3. `hr.employee_profile.updated` — cập nhật profile nhân viên (role, department, account_type)
- **Durable consumer:** mỗi topic có durable name riêng, đảm bảo at-least-once delivery
- **Idempotency:** `QueryNatsEventHandler` track `event_id` đã xử lý (LRU, TTL 24h) để tránh duplicate

### PostgreSQL
- **asyncpg** connection pool
- **4 table chính:** `conversations/messages`, `document_access`, `notifications`, `user_access_profiles`
- **Mock mode:** `DATABASE_URL=None` → dùng in-memory repo (dict)

### Redis
- **Rate limiter:** sliding window, `RATE_LIMITER_MODE=redis`. Fallback: in-memory (không persist giữa restart)
- **Production bắt buộc:** `RATE_LIMITER_MODE=redis` required khi `APP_ENV=production`

### OpenAI API
- **Responses API** (không phải Chat Completions) — dùng cho cả triage, think, và streaming answer
- **Model:** `openai_llm_model` (default `gpt-4o-mini`), embedding: `openai_embedding_model`
- **Adapter:** `OpenAIResponsesChatModel` — LangChain `BaseChatModel` wrapper để tương thích với LangGraph `bind_tools()`

### Langfuse
- **Khi nào:** `OBSERVABILITY_MODE=langfuse`, cần `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`
- **Gì:** LangChain `CallbackHandler` — tự động capture mọi span (node/LLM/tool) của LangGraph

### llm-guard
- **Khi nào:** `GUARDRAILS_MODE=llm_guard` (bắt buộc production)
- **Input:** `PromptInjection` scanner — block prompt injection trước khi chạm LLM
- **Output:** `Anonymize` scanner — redact PII (email, phone) khỏi câu trả lời cuối

---

## 5. Cơ chế bảo vệ (Security & Resilience)

### ACL (Access Control List)
- `DocumentAccessRepo.get_allowed_doc_ids(user_id, role, department, account_type)` — mỗi request fetch danh sách tài liệu cho phép
- `document_ids` được inject **server-side** vào MCP call, LLM không bao giờ nhìn thấy hoặc override được
- `user_id` inject tương tự vào `hr_query` — người dùng chỉ xem được dữ liệu HR của chính mình
- ACL post-filter thêm: sau khi mcp-service trả về kết quả, query-service lọc lại một lần nữa theo `allowed_doc_ids`

### Reserved params
- `user_id`, `document_ids`, `top_k` bị strip khỏi tool schema trước khi gửi cho LLM (`_strip_reserved_params()`)
- LLM không thể yêu cầu xem tài liệu của người khác hay vượt `top_k` limit

### Rate Limiting
- 20 request/phút/user (configurable `QUERY_RATE_LIMIT_PER_MINUTE`)
- Sliding window, per-user (user_id)

### Circuit Breaker
- Tự động ngắt kết nối mcp-service khi liên tục lỗi
- State: closed → open (sau N lỗi) → half-open → closed (sau timeout)
- Health endpoint phản ánh trạng thái circuit

### Shortcut node (zero API cost)
- `classify_shortcut()` kiểm tra **deterministic rules** TRƯỚC bất kỳ LLM call nào
- Thứ tự ưu tiên: emergency → injury → distress → identity → user_profile → security → cross_user → it_support → off_topic → clarify
- Emergency/injury/distress nhận canned response ngay, không gọi LLM hay tool

### Dedup guard (LangGraph loop)
- `act_node` track signature `(tool_name, args)` đã thực thi
- Phát hiện duplicate → set `force_answer=True` → `think_node` emit final text answer, không loop thêm
- `observe_node` set `force_answer=True` khi đạt `max_iterations` (default 3)

### Semantic cache namespace
- Cache key = SHA-256 của sorted document_ids → người dùng khác ACL không share cache nhầm

---

## 6. Các chế độ vận hành (Environment Variables)

| Biến | Giá trị | Ý nghĩa |
|------|---------|---------|
| `AUTH_MODE` | `mock` / `jwt` / `user_service` | Xác thực người dùng |
| `MCP_MODE` | `mock` / `real` | Kết nối mcp-service hay dùng mock data |
| `LLM_MODE` | `mock` / `openai` | Dùng mock client hay OpenAI thật |
| `NATS_MODE` | `mock` / `nats` | Subscribe NATS hay bỏ qua |
| `USE_LANGGRAPH` | `true` / `false` | Dùng LangGraph agent hay legacy orchestration |
| `AGENT_MODE` | `guarded` | Chế độ agent (hiện chỉ có guarded) |
| `AGENT_MAX_ITERATIONS` | `3` | Số lượt think→act tối đa |
| `GUARDRAILS_MODE` | `off` / `llm_guard` | Bật/tắt llm-guard |
| `OBSERVABILITY_MODE` | `off` / `langfuse` | Bật/tắt Langfuse tracing |
| `RATE_LIMITER_MODE` | `memory` / `redis` | Rate limiter backend |
| `TOOL_ROUTING_MODE` | `legacy` / `native` | hr_query dùng typed method hay generic call_tool |
| `MCP_TOOL_CACHE_TTL_SECONDS` | `0` | Cache TTL cho list_tool_specs() (0=off) |
| `APP_ENV` | `development` / `production` | Production enforce nhiều constraint |

**Chế độ development (tất cả mock):**
```
AUTH_MODE=mock MCP_MODE=mock LLM_MODE=mock NATS_MODE=mock USE_LANGGRAPH=false
```
Không cần bất kỳ external service nào. Chạy được hoàn toàn offline.

**Chế độ production:**
```
APP_ENV=production AUTH_MODE=jwt MCP_MODE=real LLM_MODE=openai NATS_MODE=nats
USE_LANGGRAPH=true GUARDRAILS_MODE=llm_guard OBSERVABILITY_MODE=langfuse
RATE_LIMITER_MODE=redis
```
Validator tại startup (`Settings.validate_runtime_config`) fail fast nếu thiếu.

---

## 7. Dynamic Tool Discovery (Issue #43)

Từ phiên bản hiện tại, query-service **tự động phát hiện tool mới** từ mcp-service mà không cần sửa code routing:

**Cơ chế:**
1. Startup: `LangChainMCPToolsLoader.warmup()` gọi `list_tool_specs()` từ mcp-service, log tool list
2. Per-request (`think_node`): `get_acl_tools()` gọi lại `list_tool_specs()`, build tool schema động:
   - `rag_search` → StructuredTool bespoke (ACL doc_ids + score filter + sources)
   - `hr_query` → StructuredTool bespoke (inject user_id, typed schema)
   - Tool mới bất kỳ → `{"type":"function", "name":…, "parameters":…}` dict (generic)
3. `act_node`: `rag_search/hr_query` giữ xử lý riêng; tool khác → `mcp_client.call_tool()` + stream `summary`
4. Legacy path: `_choose_route` truyền `discovered_tools` → `route_decision` chấp nhận tool name từ set đã discover
5. Mock: `MockMCPClient.register_tool(spec, response)` — test thêm tool thứ 3, không sửa routing

**Để thêm tool summary-style vào production:**
1. Implement tool mới trong mcp-service (trả về `{"summary": "..."}`)
2. Deploy mcp-service
3. query-service tự discover tại next request — **0 dòng code thay đổi**

---

## 8. API Endpoints

| Method | Path | Mô tả |
|--------|------|-------|
| `POST` | `/query` | Gửi câu hỏi → SSE stream (token events + done event) |
| `GET` | `/conversations` | Lịch sử hội thoại của user |
| `DELETE` | `/conversations` | Xóa lịch sử |
| `GET` | `/notifications` | Danh sách thông báo tài liệu mới |
| `PATCH` | `/notifications/{id}/read` | Đánh dấu đã đọc |
| `POST` | `/feedback` | Gửi feedback cho câu trả lời |
| `GET` | `/health` | Health check (db, redis, mcp, nats, circuit) |
| `GET` | `/admin/*` | Admin endpoints (chỉ khi `ENABLE_DEV_ENDPOINTS=true`) |

**Format SSE (`POST /query`):**

```
data: {"token": "Bạn còn ", "phase": "generating", "session_id": "...", "iterations": 1}
data: {"token": "12 ngày nghỉ", "phase": "generating", ...}
data: {"phase": "acting", "tool": "hr_query", "tool_args": {"intent": "leave_balance"}, ...}
data: {"done": true, "outcome": 5, "sources": [], "session_id": "...", "iterations": 1}
```

`outcome` là giá trị int của enum `Outcome` (SUCCESS=5, NO_INFO=3, REFUSE=1, CLARIFY=2, OFF_TOPIC=4, ERROR=6).

---

## 9. Tại sao thiết kế như vậy?

### LangGraph thay vì ReAct text loop
LangGraph quản lý state machine rõ ràng (shortcut → triage → think → act → observe → answer). Mỗi node có trách nhiệm độc lập, dễ test riêng. Không phụ thuộc vào LLM parse THOUGHT/ACTION text — dùng native `tool_calls`.

### Tách shortcut_node khỏi triage_node
- Shortcut (emergency/security/identity): deterministic rule matching, **không gọi API**, độ trễ ~0ms
- Triage: LLM call, dùng khi câu hỏi cần ngữ cảnh để phân loại (in_scope/off_topic/clarify)
- Tiết kiệm ~1 API call cho ~30-40% câu hỏi thông thường

### ACL inject server-side, không tin LLM
LLM biết **tên tool** và **args model cần**, nhưng không bao giờ biết `document_ids` hay `user_id` thực sự. Hai giá trị này inject tại `act_node` từ `state` (được set tại entry từ authenticated user + DB). Ngay cả prompt injection cũng không thể vượt qua.

### Semantic cache với namespace ACL
Nếu Alice và Bob có quyền xem tài liệu khác nhau, cache của họ được namespace riêng (hash của doc_ids). Câu hỏi giống nhau nhưng ACL khác → không share cache.

### Circuit breaker cho mcp-service
Khi mcp-service down, circuit breaker tự mở sau N lỗi liên tiếp. Mọi request trong thời gian đó trả về lỗi ngay (không hang) và health endpoint báo `mcp_circuit: open`.

### Dynamic tool discovery
`ACL_WHITELIST` hardcode bị loại bỏ khỏi `get_acl_tools()`. Bất kỳ tool nào mcp-service khai báo trong `list_tool_specs()` đều tự động được bind vào model và thực thi được — không cần release query-service.

---

## 10. Chạy local

```bash
cd src/query-service

# Development (all mock, no external services needed)
cp .env.example .env   # hoặc tạo file .env với nội dung dưới
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
