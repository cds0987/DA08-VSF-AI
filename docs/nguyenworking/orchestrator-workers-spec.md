# Query-Service — Orchestrator-Workers Refactor (MOSA)

> Spec triển khai. Mục tiêu: giảm latency + thêm memory + cấu trúc multi-agent cắm-tháo.
> Giữ flow `react` cũ song song (rollback bằng 1 dòng manifest).

## 0. Bối cảnh & vấn đề (đã verify bằng code, 2026-06-19)

- Flow prod hiện tại (`AGENT_MERGED_REASON=true`): `shortcut → think → act → observe → (loop think) → answer`.
- Model thật qua ai-router (`routing.yaml`): `think → deepseek/deepseek-v4-pro`, `answer → deepseek/deepseek-v4-flash`. `gpt-5.4-nano` chỉ là fallback khi không route.
- `hr_query` LUÔN bật (bind cứng `tools=[rag_search, hr_query]` ở `langgraph_nodes.py:105`; KHÔNG có flag tắt — docs cũ sai).
- **Điểm yếu:**
  1. Latency: query RAG điển hình = 2× think-pro + 1 flash **tuần tự**; `act_node` chỉ chạy `tool_calls[0]` (không song song).
  2. Memory yếu: chỉ K=4 message thô (`orchestration.py:371`), không summarization/vector.

## 1. Kiến trúc đích

```
input
  ▼
think / ROUTER  (deepseek-v4-pro, 1 call, structured output)
  │   ├─ route = LIGHT  → answer (flash)            # không cần fetch data nội bộ
  │   └─ route = HEAVY  → plan: steps[role,input,direction] + DAG(depends_on)
  ▼ (HEAVY)
dispatch ──Send API──► [worker, worker, ...]  (gpt-5.4-mini, SONG SONG)
  ▲                        │  mỗi worker: fetch data + phân tích theo direction
  │                        ▼
  └─ join ◄── results (state reducer merge) ◄┘
        ▼ (còn level chưa chạy → quay dispatch)
   answer / SYNTHESIZE  (deepseek-v4-flash) → stream
        ▼
   critic (optional, flag, mặc định tắt) → PASS → END | FAIL(≤max_replan) → orchestrate
```

**Nguyên tắc allocate model:**
| Tầng | Role | Capability (routing.yaml) | Model | Fallback |
|------|------|---------------------------|-------|----------|
| Router/Orchestrator | think | `think` | deepseek-v4-pro | gpt-4o-mini (cạn key deepseek) |
| Worker song song | worker | `worker` (MỚI) | **gpt-5.4-mini** | gpt-4o-mini (cạn 5 key OpenAI) |
| Synthesize | answer | `answer` | deepseek-v4-flash | gpt-4o-mini |

- **Router = deepseek-pro** (không dùng mini gate vì mini bất ổn). Chỉ **1 lần gọi pro/query** → hết nút thắt latency.
- **Mini chỉ ở tầng worker**: lỗi 1 worker ≠ hỏng cả câu; có fallback + banded rotation 5 key.

### LIGHT vs HEAVY (router tự quyết, trong 1 structured output)
- **LIGHT**: chào hỏi, meta (hỏi lại lịch sử), refuse, trả lời từ context/history — không fetch data → answer(flash) thẳng.
- **HEAVY**: cần ≥1 retrieval/HR/analysis. RAG đơn = HEAVY với 1 worker (song song suy biến) — **chỉ 1 cơ chế executor**.

## 2. ai-router — capability `worker` mới (routing.yaml)

```yaml
capabilities:
  worker:                           # subagents song song
    tiers: [free_oai]               # gpt-5.4-mini, KHÔNG OpenRouter
    models:
      free_oai: openai/gpt-5.4-mini
    selector:
      impl: banded_rotation         # xoay 5 key OpenAI
      params:
        band_tokens: 2500000        # ~quota/key/ngày → cạn thì xoay key kế
        save_mode:                  # CẠN CẢ 5 KEY → degrade gpt-4o-mini
          enabled: true
          model: openai/gpt-4o-mini
          tier: free_oai
          band_tokens: 2500000
```
**Cần kiểm chứng:** `gpt-5.4-mini` phải có trong `model_catalog.json` (build_catalog); xác nhận quota 2.5M là **token**/key/ngày; 5 key cùng pool router xoay.

## 3. Cấu trúc thư mục (MOSA, theo convention repo)

```
query-service/app/
  agents/                         # MỚI
    registry.py                   # clone Registry[T] của mcp-service (decorator + entry-points)
    base.py                       # AgentRole ABC: name, capability, tools, run(WorkerInput)->WorkerOutput
    plan_schema.py                # JSON Schema plan — validate output orchestrator (retry khi sai)
    bus.py                        # WorkerInput/Output + reducer merge_step_results
    graph_builder.py              # build LangGraph theo manifest (Send/dispatch/join)
    roles/  rag_retrieve.py  hr_lookup.py  analyze.py  synthesize_recommend.py  critic.py
    planners/  orchestrator_workers.py   react.py (wrap flow cũ)
    memory/  recent_buffer.py  summary_buffer.py  vector.py
  agents.yaml                     # MANIFEST hot-config (fallback-safe + CI lint)
  application/langgraph_*.py      # GIỮ — react path cũ (rollback)
```

## 4. Bus contract (chống ghi đè khi N worker song song)

```python
WorkerInput  = {step_id, role, input, direction, upstream: {dep_id: output}}
WorkerOutput = {step_id, role, output, sources: [...], status: ok|no_info|error}

class AgentState(TypedDict):
    plan: Plan
    results: Annotated[dict[str, WorkerOutput], merge_step_results]  # reducer hợp dict
    ...
# worker chỉ return {"results": {step_id: out}} → reducer merge, KHÔNG clobber
```
- `dispatch` = conditional edge trả `list[Send("worker", WorkerInput)]` cho các step có `depends_on` đã đủ trong `results`.
- `join` rà `results` vs `plan`: còn level → `dispatch`; xong → `synthesize`.

## 5. Plan schema (orchestrator output)

```json
{
  "route": "light | heavy",
  "answer_hint": "string (khi light)",
  "steps": [
    {"id": 1, "role": "rag_retrieve", "input": "...", "direction": "...", "depends_on": []},
    {"id": 2, "role": "hr_lookup", "input": {"intent": "leave_balance"}, "direction": "...", "depends_on": []},
    {"id": 3, "role": "synthesize_recommend", "direction": "...", "depends_on": [1,2]}
  ]
}
```
- `role` enum = `registry.available()` (catalog động — thêm role tự xuất hiện).
- Validate bằng JSON Schema; sai → retry (như StructuredOutput).

## 6. Manifest agents.yaml

```yaml
version: 1
mode: orchestrator_workers        # | react (rollback)
planner: orchestrator_workers
memory: {impl: summary_buffer, keep_recent: 4, summarize_after: 8}
roles:
  - {name: rag_retrieve,         capability: worker, tools: [rag_search]}
  - {name: hr_lookup,            capability: worker, tools: [hr_query]}
  - {name: analyze,              capability: worker, tools: []}
  - {name: synthesize_recommend, capability: answer, tools: []}
  - {name: critic,               capability: worker, enabled: false}
max_replan: 1
max_workers_per_level: 4
worker_timeout_seconds: 30
```
- Loader thiếu/sai → fallback `mode: react` (không vỡ service).
- CI manifest-lint: role.name ∈ Agent Registry, tools ∈ mcp tool specs, capability ∈ routing.yaml.

## 7. Mini bất ổn — biện pháp bắt buộc
- Per-worker: retry 1 lần → degrade (save_mode 4o-mini) → nếu vẫn fail trả `status: error`, synthesize chạy với phần còn lại.
- `direction` tường minh (router viết rõ) → mini chỉ thực thi, ít reasoning.
- Bounded: `max_workers_per_level` + `worker_timeout_seconds`.

## 8. Milestone (mỗi bước có verify, confirm trước khi sang bước kế)
1. **Skeleton MOSA**: Registry + base + plan_schema + manifest loader (fallback). *Verify: unit test + manifest-lint CI.*
2. **Bus + reducer**: `merge_step_results`. *Verify: test 3 worker song song không clobber.*
3. **Roles**: rag_retrieve, hr_lookup, synthesize_recommend wrap tool/model sẵn. *Verify: test từng role.*
4. **routing.yaml capability `worker`** + catalog model. *Verify: ai-router test route → gpt-5.4-mini, save_mode → 4o-mini.*
5. **Orchestrator (router)**: plan schema validated, LIGHT/HEAVY. *Verify: eval query mẫu — plan đúng role/DAG.*
6. **graph_builder + Send/dispatch/join**: fan-out động. *Verify: e2e multi-part chạy song song, đo latency vs react.*
7. **Memory summary_buffer**. *Verify: hội thoại dài giữ ngữ cảnh.*
8. **Critic + feedback** (flag, mặc định tắt).
9. **A/B prod**: bật `mode` % traffic, so latency + chất lượng (Langfuse), rollback nếu xấu.

## 9. Invariants
- 1 lần gọi deepseek-pro/query (router); không loop think.
- Worker không đọc/ghi state worker khác ngoài qua reducer.
- `mode: react` luôn rollback được, không xóa code cũ.
- Model allocate chỉ đổi qua capability (routing.yaml) + agents.yaml, không hardcode.
```
