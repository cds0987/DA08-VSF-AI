# Hợp đồng SSE (FE ↔ query-service) — 1 nguồn sự thật

> TL;DR: Mọi event query-service đẩy ra FE (`phase`/`node`/`tool`/done) khai **MỘT chỗ**:
> [`app/agents/sse_contract.py`](../app/agents/sse_contract.py). FE render **generic** theo file
> sinh ra. Thêm node/phase/tool mà quên khai → **CI đỏ** (không bao giờ "câm" trên UI).

## Vì sao có file này
Trước đây hợp đồng SSE nằm rải rác (literal `"phase":"..."` khắp graph_builder/roles/orchestration)
+ hardcode ở FE. Thêm 1 node vào graph mà quên cho FE biết → event ra UI bị **bỏ qua âm thầm**
(không lỗi, chỉ mất khúc hiển thị / tin nhắn treo). Giờ gom về 1 contract + gate 2 đầu.

## Kiến trúc (2 đầu, 1 nguồn)
```
app/agents/sse_contract.py   ← NGUỒN DUY NHẤT (Python)
  PHASES, NODES (NodeDescriptor: label+group+icon), GROUPS, TOOLS, DONE_REQUIRED
        │  python scripts/gen_sse_contract.py   (codegen)
        ▼
src/frontend/chat/app/types/sse-contract.gen.ts   ← FE đọc (KHÔNG sửa tay)
  MessageSteps.vue / Pipeline.vue render theo nodeGroup() + SSE_GROUPS
  stores/chat.ts dùng SSE_DONE_REQUIRED (guard done-event)
```
- Backend phát event qua `ctx.emit({...})`; `_emit_guard()` (orchestration.py) soi theo contract,
  **chỉ cảnh báo** ở prod (fail-safe, không làm vỡ câu trả lời), log drift.
- `node` tự mô tả cách hiển thị → FE **không hardcode** danh sách node. Node lạ chưa khai →
  `nodeGroup()` fallback `orchestrator` (vẫn hiện).

## ➕ Thêm 1 NODE mới vào graph/agent (vd node "critique")
1. Khai trong [`sse_contract.py`](../app/agents/sse_contract.py):
   ```python
   NODES = {
       ...
       "critique": _nd("critique", "Phản biện", "verify", "ShieldCheck"),  # group ∈ GROUPS
   }
   ```
   và thêm tên vào `_EXPECTED_NODES` trong
   [`tests/test_sse_contract_enforcement.py`](../tests/test_sse_contract_enforcement.py).
2. Sinh lại type FE:
   ```bash
   python scripts/gen_sse_contract.py
   ```
   (commit luôn file `sse-contract.gen.ts` thay đổi.)
3. Emit trong code: `await ctx.emit({"phase": "thought", "node": "critique", "text": ...})`.
   → FE **tự hiện** dưới group đã khai, không cần sửa FE.

## ➕ Thêm PHASE / TOOL mới
- Phase: thêm vào `PHASES` + `_EXPECTED_PHASES`. (FE xử lý phase trong `stores/chat.ts` `onmessage`
  — nếu phase cần hành vi mới ở FE thì thêm nhánh; nếu chỉ là thought/status thì đã có sẵn.)
- Tool: thêm vào `TOOLS` (nhãn). FE đọc `SSE_TOOLS` cho khúc "agent đã làm".

## 🔒 Gate giữ 2 đầu khớp (chạy trong CI)
- `tests/test_sse_contract_enforcement.py` (Python, job `unit query-service`):
  no-undeclared-phase, **no-silent-node**, drift snapshot, descriptor đầy đủ, done-required khớp
  FE, runtime mọi event graph hợp lệ, **sync `.gen.ts`** (quên gen lại = đỏ).
- `src/frontend/chat/tests/sse-contract.test.ts` (job `frontend-test`): cấm FE hardcode lại node,
  bắt FE import contract.

→ Đổi contract mà quên đồng bộ → đỏ **trước khi lên prod**.

## ⚠️ Bất biến KHÔNG được phá (xem thêm memory feedback của team)
- done-event LUÔN đủ `done` + `session_id:str` + `sources:array` (mỗi source có `ref:int`).
  Thiếu → tin nhắn treo. (`DONE_REQUIRED` ⇔ `isDoneEvent` ở FE.)
- Đừng bỏ stream reasoning (planner astream_plan / verify astream_reasoning) → mất stream = màn
  hình freeze.
