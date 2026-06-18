# MOSA per-node LLM adapter (query-service agent)

> Mỗi node LangGraph dùng **tập model riêng** qua **adapter cắm-tháo (MOSA)**; tách
> **think (planner/reasoning)** khỏi **answer (stream token thật)**; unit test kiểm gọi
> đúng model/param + log/trace dò bug; xử lý đúng **reasoning model** (o3-mini đã probe).

## 1. Vì sao làm
Trước refactor: `build_langgraph_agent` nhận **1 model dùng chung** (triage+think+answer).
Production route ai-router với **1 capability `think`** cho mọi node; model chọn
**per-request round-robin toàn cục** (`weighted_banded`, counter `think:wrr`) → cùng 1 câu
hỏi có thể nhiều model trả, không tái lập, chất lượng dao động.

### Probe o3-mini (gọi thẳng OpenAI — `eval/probe_o3mini.py`)
| Argument | Kết quả | Kết luận |
|---|---|---|
| `max_tokens` | ❌ 400 | dùng `max_completion_tokens` |
| `temperature` ≠ default | ❌ 400 | **bỏ temperature** |
| `top_p` | ❌ 400 | **bỏ top_p** |
| `reasoning_effort` low/med/high | ✅ (reasoning_tokens 0/192/384) | đòn bẩy độ sâu |
| role system / developer | ✅ | không remap |
| tool calling | ✅ | think dùng được |
| stream content | ✅ token thật | answer stream được |
| stream reasoning | ❌ (OpenAI ẩn) | UI cần indicator "đang nghĩ" |

`reasoning_tokens` ở `usage.completion_tokens_details.reasoning_tokens` (tính như output).

## 2. Kiến trúc
```
app/infrastructure/llm/
  base.py        # NodeLLMAdapter: transform_params(), parse_usage(), surfaces_reasoning_stream()
  registry.py    # @register("name") + get_adapter()
  adapters/
    standard.py        # model thường: giữ temperature/top_p
    reasoning_oai.py    # o3-mini: BỎ temperature/top_p, THÊM reasoning_effort   [Phase 1]
    reasoning_or.py     # deepseek: reasoning + stream reasoning_content          [Phase 1]
  profiles.yaml  # MANIFEST node -> {adapter, capability, models, reasoning_effort}
  loader.py      # đọc manifest -> NodeProfile; fallback 'standard' (kill-switch)
```
Đóng-mở: thêm model cùng họ = thêm vào `models[]`; thêm họ lạ = adapter mới + `@register`.

## 3. Graph mục tiêu (executor = node trong graph chính)
```
triage(model triage) → think(model think, planner)
   → execute(MCP, ACL/dedup) → observe → think ...
   → answer(model answer, STREAM token)
```
- think: reasoning + quyết tool/dừng. answer: tách riêng, stream. execute: đổi tên từ `act`.

## 4. Lộ trình (mỗi phase test xanh + commit/push/CI)
- **Phase 0 ✅** khung `base/registry/profiles.yaml/loader` + `standard` + test (12 ca) + PyYAML.
- **Phase 1** `reasoning_oai`/`reasoning_or` + `MosaChatModel` + test strip-temp/effort/parse.
- **Phase 2** `build_langgraph_agent(models)`; tách answer (stream); `act`→`execute`; `get_node_model`.
- **Phase 3** log/trace per-node (session_id, node, adapter, model_id, capability, effort, usage) + Langfuse tag.
- **Phase 4** verify ai-router parser bắt `reasoning_tokens`; kill-switch fallback.

## 5. Trạng thái
- [x] Phase 0 — khung + standard + test (12 passed); CI develop xanh (unit/e2e/build)
- [x] Phase 1 — `reasoning_oai`/`reasoning_or` + `MosaChatModel` + `build_node_chat_model`
      + `tests/test_mosa_adapters.py` (11 ca, tổng 23 passed). Reasoning model bỏ
      temperature/top_p, thêm reasoning_effort; usage giữ reasoning_tokens.
- [x] Phase 2 — per-node model (triage/think/answer) qua `get_node_model`; `build_langgraph_agent`
      nhận `models` dict; tách answer node sinh-chữ-riêng (flag `AGENT_SPLIT_ANSWER`, mặc định
      OFF để e2e không đổi); answer passthrough ACTION JSON; orchestration lọc token think khi
      split. `tests/test_graph_split.py` (8 ca). **act_node CHÍNH LÀ executor nối MCP** (giữ tên
      `act` để không phá hợp đồng SSE với frontend).
- [x] Phase 3 — log/trace per-node: helper `_model_trace_fields` nhúng {adapter, model_id,
      reasoning_effort} vào log `langgraph_triage_start` / `langgraph_think` / `langgraph_answer`
      (kèm session_id) → biết chính xác node nào chạy model nào. `tests/test_node_trace.py` (3 ca).
- [x] Phase 4 — ai-router `extract_usage` bắt `reasoning_tokens` (+ field `Usage.reasoning_tokens`,
      KHÔNG cộng lại vào cost vì đã nằm trong output_tokens) + `tests/test_parser_reasoning.py` (3 ca);
      kill-switch: `MosaChatModel.adapter` fallback `standard` khi adapter_name lỗi (không crash node)
      + `tests/test_mosa_killswitch.py` (3 ca).

### ⚠️ Phát hiện từ e2e (quan trọng — ngoài probe o3-mini)
Capability `think` resolve ra **gpt-5.4-mini**; think node **bind tools**. OpenAI trả:
> 400: *Function tools with reasoning_effort are not supported for gpt-5.4-mini in
> /v1/chat/completions. Please use /v1/responses instead.*

→ Trên **chat.completions**, tổ hợp **tools + reasoning_effort** KHÔNG được hỗ trợ (o-series/
gpt-5.4-mini). Xử lý:
- **profiles.yaml mặc định mọi node = `standard`** (gửi temperature, KHÔNG reasoning_effort)
  = đúng hành vi cũ → e2e xanh. Reasoning là **opt-in** khi đã sẵn sàng.
- **reasoning_oai tự bỏ reasoning_effort khi có `tools`** (phòng hờ khi opt-in).
- Muốn dùng reasoning_effort cho think (có tool): phải đi **/v1/responses**, hoặc chỉ áp
  reasoning_effort cho **answer node** (không bind tools).

### ⚠️ Phát hiện từ deploy smoke (regression triage)
Đẩy triage sang capability `triage` (gpt-4o-mini) -> model rẻ **phân loại SAI** câu RAG
("Tài liệu hướng dẫn nhân viên có gì") thành `meta` dù session mới (không có prior answer)
-> deploy smoke fail. → **triage.capability giữ = `think`** (gpt-5.4-mini) như prod cũ.
Bài học: KHÔNG hạ model triage khi chưa eval chất lượng phân loại.

**Tổng kết:** 5/5 phase xong. Test mới: query-service 37 ca (registry 12, adapters 11, graph 8,
trace 3, killswitch 3) + ai-router 3 ca. Full suite query-service: 228 passed.

### Cách bật tách answer (sau khi eval parity xanh)
```
# query-service.env
AGENT_SPLIT_ANSWER=true
```
Khi đó: think=planner (model `think`, reasoning), answer=generator (model `answer`, stream token).
Mặc định OFF: think tự sinh câu trả lời như cũ — chỉ khác là triage/think đã tách model riêng.
