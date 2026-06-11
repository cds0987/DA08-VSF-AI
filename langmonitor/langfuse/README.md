# Hướng dẫn cắm Langfuse full-step vào Query Service (không làm vỡ codebase)

> **Đối tượng:** dev query-service.
> **Mục tiêu:** từ trace hiện tại (chỉ 1 root `rag-query` + 1 generation `llm` gộp) →
> trace có **span con cho TỪNG step** thật của orchestration.
> **Ràng buộc số 1:** tracing là *best-effort*. Một lỗi tracing **không bao giờ** được làm
> vỡ / treo / chậm luồng query. Mọi đoạn dưới đây đều bọc `try/except ... pass`.

---

## 0. TL;DR cho người vội

1. Mở rộng `LangfuseTracer` thêm 2 method **opt-in**: `span(handle, name, ...)` và
   `generation(handle, name, ...)` — trả về child object hoặc `None`.
2. `CompositeTracer` forward 2 method đó xuống tracer con (giữ nguyên list-handle).
3. Trong `orchestration.py`, tại các điểm đã có sẵn event (`on_tool_start/end`,
   `on_chain_start/error`, guardrail, route decision, cache), gọi `tracer.span(...)` để
   ghi span con. **Không** đổi chữ ký `stream()` / không đụng SSE / không đụng node.
4. Backend nào (langsmith) chưa hỗ trợ method mới → `getattr(tracer, "span", None)` trả
   `None` → tự bỏ qua. Không ràng buộc 2 backend phải song song tính năng.

Toàn bộ thay đổi **thêm code, không sửa hành vi cũ** → an toàn rollback.

---

## 1. Bản đồ step của query-service (cái cần trace)

Luồng thật (xem `app/application/use_cases/query/orchestration.py` +
`app/application/langgraph_nodes.py`):

```
stream()                         ← root trace "rag-query" (ĐÃ CÓ)
 └─ _stream_inner / _stream_langgraph
     ├─ [1] input_guardrail.scan()              ← span "guardrail.input"      (MISS)
     ├─ [2] document_access_repo.get_allowed_doc_ids()  ← span "acl.resolve"  (MISS)
     ├─ [3] conversation_repo.get_context()     ← span "history.fetch"        (MISS)
     ├─ [4] _choose_route() / triage_node       ← generation "route-decision" (MISS)
     ├─ [5] semantic_cache hit/miss             ← span "cache.lookup"         (MISS)
     └─ langgraph_agent.astream_events(...)      loop:
          ├─ think_node   → on_chat_model_stream ← generation "llm.think"     (MISS, token gộp)
          ├─ act_node     → on_tool_start         ← span "tool.<name>" mở      (MISS)
          │     • rag_search → Qdrant retrieval   ← span "retrieval.qdrant"    (MISS)
          │     • hr_query   → HR Service          ← span "tool.hr_query"      (MISS)
          ├─ observe_node → on_tool_end           ← đóng span "tool.<name>"    (MISS)
          ├─ answer_node  → on_chat_model_stream   ← generation "llm.answer"   (MISS)
          └─ on_chain_error                        ← span level=ERROR          (MISS)
     finally:
        output_guardrail (nếu có)                 ← span "guardrail.output"    (MISS)
        tracer.finish(...)                         ← update outcome + usage     (ĐÃ CÓ)
```

`(ĐÃ CÓ)` = đang trace. `(MISS)` = cần cắm. Thứ tự ưu tiên gợi ý: **[4] route → tool/retrieval
→ guardrail → cache → history/acl** (giá trị debug giảm dần).

---

## 2. Nguyên tắc thiết kế (vì sao làm kiểu này)

- **KHÔNG dùng `LangchainCallbackHandler`.** Callback v2 kéo `langchain-core <1.0` → xung đột
  với `langchain-core 1.x` đang chạy → crash giữa stream. Đây là lý do gốc cả file
  `langfuse_tracing.py` dùng low-level client. **Tuyệt đối không** quay lại callback.
- **Span con tạo thủ công từ low-level client.** Langfuse v2 client cho phép:
  `trace.span(name=..., start_time=..., input=...)` và `span.end(output=..., end_time=...)`,
  tương tự `trace.generation(...)`. Ta gọi trực tiếp các API này.
- **Interface tracer mở rộng kiểu opt-in.** Orchestration hiện chỉ biết `start()/finish()`.
  Ta thêm method mới nhưng gọi qua `getattr` → tracer cũ / backend chưa hỗ trợ vẫn chạy.
- **Handle opaque.** Orchestration không được biết bên trong handle là gì (Langfuse trace vs
  LangSmith RunTree). Mọi method nhận `handle` và tự xử lý `None`.

---

## 3. Bước 1 — Mở rộng `LangfuseTracer` (file `langfuse_tracing.py`)

Thêm 2 method vào class `LangfuseTracer`. **Không sửa** `start()` / `finish()` hiện có.

```python
def span(
    self,
    handle: "_TraceHandle | None",
    name: str,
    *,
    input: Any = None,
    metadata: dict | None = None,
) -> Any | None:
    """Mở 1 span con dưới root trace. Trả span object (để .end sau) hoặc None.

    Best-effort: handle None / langfuse lỗi -> trả None, caller cứ gọi end_span(None)
    cũng không sao."""
    if handle is None:
        return None
    try:
        return handle.trace.span(
            name=name,
            start_time=datetime.now(timezone.utc),
            input=input,
            metadata=metadata or {},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("langfuse_span_start_failed", extra={"error": str(exc)[:200]})
        return None

@staticmethod
def end_span(span: Any | None, *, output: Any = None, level: str | None = None) -> None:
    """Đóng span con. span None -> no-op. level='ERROR' để đánh dấu bước lỗi."""
    if span is None:
        return
    try:
        kwargs: dict[str, Any] = {"end_time": datetime.now(timezone.utc), "output": output}
        if level:
            kwargs["level"] = level  # langfuse v2: 'DEFAULT' | 'WARNING' | 'ERROR'
        span.end(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("langfuse_span_end_failed", extra={"error": str(exc)[:200]})
```

> Nếu muốn trace 1 LLM step phụ (route-decision, think, answer) **có token/cost riêng**,
> dùng `handle.trace.generation(...)` thay vì `.span(...)` — y hệt cách `finish()` đang làm,
> chỉ khác là gọi giữa luồng. Có thể tách thêm helper `child_generation(handle, name, usage_meta)`
> tái dùng `_build_usage()`.

**Không** flush ở mỗi span — chỉ flush 1 lần ở `finish()` như cũ (flush nhiều = chậm + tốn).

---

## 4. Bước 2 — `CompositeTracer` forward method mới (file `tracing.py`)

`CompositeTracer` phải fan-out `span`/`end_span` xuống tracer con **chỉ khi con có**:

```python
def span(self, handle, name, **kwargs):
    if not handle:
        return None
    children = []
    for tracer, child_handle in handle:
        fn = getattr(tracer, "span", None)
        if fn is None:
            continue
        try:
            children.append((tracer, fn(child_handle, name, **kwargs)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("composite_span_failed", extra={"error": str(exc)[:200]})
    return children or None

def end_span(self, span_handle, **kwargs):
    if not span_handle:
        return
    for tracer, child_span in span_handle:
        fn = getattr(tracer, "end_span", None)
        if fn is None:
            continue
        try:
            fn(child_span, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("composite_end_span_failed", extra={"error": str(exc)[:200]})
```

> Lưu ý: composite handle là `list[(tracer, child_handle)]`, nên span handle cũng là list
> cùng cấu trúc → `end_span` lặp đúng cặp. Backend chưa có `span` (vd LangSmith giai đoạn
> đầu) tự bị `continue` bỏ qua.

---

## 5. Bước 3 — Cắm vào orchestration (file `orchestration.py`)

### 5.1 Quy ước gọi an toàn

Luôn lấy method qua `getattr` để code chạy được cả khi tracer = None / tracer cũ:

```python
def _span(self, handle, name, **kw):
    fn = getattr(self._tracer, "span", None)
    return fn(handle, name, **kw) if fn else None

def _end_span(self, span, **kw):
    fn = getattr(self._tracer, "end_span", None)
    if fn:
        fn(span, **kw)
```

`handle` ở đây là `trace` object do `tracer.start()` trả về. **Vấn đề hiện tại:** `trace`
đang được tạo *lazily* trong wrapper `stream()` (sau event đầu), còn các step như guardrail
chạy trong `_stream_inner` **trước** khi có trace. → Xem mục 6 để xử lý thứ tự.

### 5.2 Span quanh tool call (giá trị cao nhất, dễ nhất)

Trong `_stream_langgraph`, vòng `astream_events`, ta đã có `on_tool_start` / `on_tool_end`.
Giữ 1 dict map tool đang mở:

```python
open_tool_spans: dict[str, Any] = {}

elif event_type == "on_tool_start":
    tool_name = event["name"]
    input_data = event.get("data", {}).get("input", {})
    open_tool_spans[tool_name] = self._span(
        trace, f"tool.{tool_name}", input=input_data,
    )
    yield { ... }   # SSE giữ NGUYÊN

elif event_type == "on_tool_end":
    tool_name = event["name"]
    output_data = event.get("data", {}).get("output", "")
    self._end_span(
        open_tool_spans.pop(tool_name, None),
        output=str(output_data)[:500],
    )
    yield { ... }   # SSE giữ NGUYÊN
```

> `rag_search` chạy retrieval Qdrant *bên trong* tool → nếu muốn span `retrieval.qdrant`
> riêng, cắm trong `langgraph_nodes.build_langgraph_tools.rag_search` (cần truyền tracer +
> handle vào tool factory — xem mục 7, làm sau).

### 5.3 Span lỗi graph

```python
elif event_type == "on_chain_error":
    error_msg = ...
    err_span = self._span(trace, "graph.error", input={"node": event.get("name")})
    self._end_span(err_span, output={"error": error_msg}, level="ERROR")
    logger.error("langgraph_stream_error", ...)
```

### 5.4 Span guardrail / route / cache

Bọc trực tiếp quanh lời gọi, ví dụ guardrail input:

```python
g_span = self._span(trace, "guardrail.input", input={"len": len(question)})
blocked, reason = await self._input_guardrail.scan(question)
self._end_span(g_span, output={"blocked": blocked, "reason": reason},
               level="WARNING" if blocked else None)
```

Route decision (`_choose_route`) nên dùng **generation** (có token) thay vì span thuần.

---

## 6. Xử lý "trace tạo lazily" — đừng để mất span đầu luồng

Hiện `tracer.start()` chỉ chạy ở event đầu trong `stream()`. Các step `[1]–[5]` (guardrail,
ACL, history, route, cache) chạy *trước* event đầu nên lúc đó `trace=None` → span sẽ rớt.

Hai cách, chọn 1:

- **(Khuyến nghị) Tạo trace sớm.** Vì `session_id` được sinh ngay đầu `_stream_inner`
  (`session_id = str(uuid4())`), chuyển `tracer.start()` lên đầu luồng (truyền session_id
  vào trực tiếp thay vì lấy từ event đầu). Khi đó mọi step đều có `trace`. Vẫn giữ
  `trace_session` override cho smoke CI. *Đây là thay đổi nhỏ, đáng làm.*
- **(Tối thiểu) Chỉ trace các step trong vòng agent.** Bỏ qua guardrail/route đầu luồng ở
  v1, chỉ cắm tool/error (mục 5.2–5.3) vì chúng nằm sau khi trace đã tồn tại. An toàn tuyệt
  đối, không đụng thứ tự khởi tạo.

> Làm v1 theo cách tối thiểu trước (tool + error), rồi v2 nâng `start()` lên sớm để phủ
> guardrail/route/cache.

---

## 7. Trace bên trong tool (retrieval Qdrant) — làm sau

`rag_search` / `hr_query` được dựng trong `build_langgraph_tools()`
(`langgraph_nodes.py:57`). Để có span `retrieval.qdrant` (số chunk, score, doc filter),
cần truyền `tracer` + `trace handle` xuyên xuống tool factory. Vì closure tool được tạo
**1 lần/agent** còn handle là **per-request**, cách sạch là dùng `contextvars.ContextVar`
giữ handle hiện tại của request, tool đọc ra. → Tách thành PR riêng, **không** gộp vào v1.

---

## 8. Checklist review trước khi merge

- [ ] Không có lời gọi tracing nào nằm ngoài `try/except` (kể cả trong helper).
- [ ] Không thêm `flush()` trong vòng lặp (chỉ `finish()` flush).
- [ ] Chữ ký `stream()` / `_stream_inner` / SSE event **không đổi** (frontend không bị ảnh hưởng).
- [ ] Tắt observability (`OBSERVABILITY_MODE=off`) → query vẫn chạy, không AttributeError.
- [ ] Backend chỉ-langsmith (chưa có `span`) → `getattr` trả None, không crash.
- [ ] Test mock mode (không OpenAI key) đi nhánh legacy `_stream_inner` vẫn pass.
- [ ] Đo p95 latency query trước/sau: chênh < 5ms (span chỉ là I/O nền best-effort).

---

## 9. Cách verify nhanh

1. Local: `OBSERVABILITY_MODE=langfuse` + key trong `deploy/env/query-service.env`.
2. Bắn 1 query có dùng tool (rag_search) → mở dashboard Langfuse (SSH tunnel
   `ssh -L 3100:localhost:3100 <vm>`, login `admin@company.com`).
3. Trace `rag-query` phải có cây con: `tool.rag_search` (+ retrieval nếu làm mục 7),
   `graph.error` khi lỗi, generation `llm`.
4. Trace smoke CI vẫn vào session `ci-smoke` để deploy kế tự purge (không đụng cơ chế cũ).

---

## 10. Phạm vi v1 (chốt lại)

**Làm ngay:** mục 3, 4, 5.2 (tool span), 5.3 (error span). → Đã thấy được tool nào chạy,
args/result, latency mỗi tool, và bước nào fail.

**v2 (sau):** mục 6 (trace sớm) + 5.4 (guardrail/route/cache).

**v3 (sau nữa):** mục 7 (retrieval Qdrant nội bộ tool) + token per-step.

LangSmith áp dụng **cùng pattern** (RunTree `create_child`) — viết ở `../langsmith/` sau khi
Langfuse v1 chạy ổn.
