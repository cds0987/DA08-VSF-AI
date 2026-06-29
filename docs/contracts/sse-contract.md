---
last-verified: 59551e39 (2026-06-29)
code-refs:
  - src/query-service/app/agents/sse_contract.py
  - scripts/gen_sse_contract.py
  - src/frontend/chat/app/types/sse-contract.gen.ts (sinh tự động)
---

# Hợp đồng SSE chat (query-service → FE)

T1 — sinh từ code. Nguồn sự thật DUY NHẤT: `sse_contract.py`. FE đọc qua TS sinh
tự động (`gen_sse_contract.py` → `sse-contract.gen.ts`); CI gate `git diff --exit-code`
file `.gen.ts` đỏ nếu quên regen sau khi đổi contract. Cả 2 đầu (Python emit + TS
consume) dùng chung manifest, drift = CI đỏ.

`CONTRACT_VERSION = 1`.

## Loại event (PHASES — tập `phase` hợp lệ)

`PHASES` (frozenset) — event mang `phase` PHẢI ∈ tập này, else FE bỏ qua âm thầm:

| phase        | kèm theo                          | ý nghĩa |
|--------------|-----------------------------------|---------|
| `thinking`   | status (thinkingStatus)           | node bắt đầu nghĩ |
| `acting`     | tool (+tool_args)                 | gọi tool |
| `observing`  | tool (+tool_result_summary)       | tool trả kết quả |
| `generating` | token                             | token câu trả lời chạy dần |
| `plan`       | route + steps[]                   | orchestrator phát kế hoạch |
| `step`       | step_id + status                  | 1 node đổi trạng thái |
| `thought`    | node + text                       | model đang nghĩ (reasoning/prose) |
| `model_used` | node + model                      | model THẬT 1 node đã chạy |

Event chỉ mang `token` (không `phase`) vẫn hợp lệ (token delta).

## NodeDescriptor (mỗi node TỰ MÔ TẢ)

`NODES` là chỗ DUY NHẤT khai node. Thêm node vào graph → thêm 1 `NodeDescriptor`
(`name`, `label`, `group`, `icon` lucide); `group` PHẢI ∈ `GROUPS` (assert). Thiếu
khai → gate test "no undeclared node" đỏ → tránh node "câm" trên UI.

`GROUPS` (có thứ tự render): `orchestrator → worker → verify → answer`.

Node hiện khai:

| node          | label                 | group        | icon |
|---------------|-----------------------|--------------|------|
| `orchestrate` | Điều phối             | orchestrator | GitBranch |
| `plan`        | Lập kế hoạch          | orchestrator | GitBranch |
| `think`       | Suy luận              | orchestrator | Sparkles |
| `act`         | Hành động             | worker       | Search |
| `verify`      | Kiểm tra & tổng hợp   | verify       | ShieldCheck |
| `answer`      | Soạn câu trả lời      | answer       | Sparkles |

## TOOLS (nhãn — khớp FE TOOL_LABEL)

`rag_search`, `hr_query`, `leave_approvals`, `resolve_date`, `leave_types`.

## Done-event bất biến

`DONE_REQUIRED = {done, session_id, sources}`. FE chỉ chốt tin nhắn khi đủ các field
này (đúng type); thiếu 1 → event bị bỏ qua → tin nhắn TREO.

- `done`: `true`
- `session_id`: string
- `sources`: ARRAY (mỗi nguồn có `ref` kiểu int — tham chiếu citation)

`validate_event(ev, strict=)` soi event theo hợp đồng:
- done-event: phải đủ `DONE_REQUIRED`.
- event thường: `phase` (nếu có) ∈ `PHASES`; `node` (nếu có) ∈ `NODES`.
- `strict=True` → raise (DÙNG TRONG TEST). Prod gọi `strict=False` → chỉ log cảnh
  báo, KHÔNG bao giờ làm vỡ câu trả lời (fail-safe).

## Manifest → codegen

`contract_manifest()` xuất JSON `{version, groups, nodes{label,group,icon}, phases,
tools, done_required}` → `gen_sse_contract.py` sinh TS cho FE.
