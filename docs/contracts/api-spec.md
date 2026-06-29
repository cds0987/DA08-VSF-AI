---
last-verified: 59551e39 (2026-06-29)
code-refs:
  - infra/http/hr-service-contract.yaml
  - infra/ci/http_contract_lint.py
  - src/hr-service/app/api/routes.py
  - src/query-service/app/infrastructure/external/hr_leave_client.py
  - src/mcp-service/app/tools/leave_write.py
---

# Hợp đồng HTTP liên-service

T1 — sinh từ code. Phạm vi gate hiện tại: seam **HTTP đơn nghỉ hr-service**. Server
Pydantic của hr-service là NGUỒN SỰ THẬT; client (query-service `HRLeaveClient`,
mcp-service `LeaveWriteTool`) dựng dict thô — không có compile-error nối 2 bên.

Gate `http_contract_lint.py` (thuần AST, lệch = exit 1):
- `server_model` (Pydantic) → field `required` = `AnnAssign` KHÔNG có default value.
- client fn → gom mọi string-literal dict key.
- ÉP: `required ⊆ client_keys` (client gửi đủ field bắt buộc, else 422 lúc chạy).
- client_key ∉ all_fields → chỉ CẢNH BÁO (Pydantic bỏ qua extra).

## Endpoint hr-service (gated)

Server file: `src/hr-service/app/api/routes.py`.

| endpoint     | method | path                                          | server_model           |
|--------------|--------|-----------------------------------------------|------------------------|
| leave_create | POST   | `/hr/leave-requests`                          | `LeaveCreateRequest`   |
| leave_update | PATCH  | `/hr/leave-requests/{request_id}`             | `LeaveUpdateRequest`   |
| leave_cancel | POST   | `/hr/leave-requests/{request_id}/cancel`      | `LeaveCancelRequest`   |
| leave_decide | POST   | `/hr/leave-requests/{request_id}/{action}`    | `ApprovalActionRequest`|

## Client per endpoint (gated)

| endpoint     | client file                                                       | fn |
|--------------|-------------------------------------------------------------------|-----|
| leave_create | query-service `…/external/hr_leave_client.py`                     | `create` |
| leave_create | mcp-service `…/tools/leave_write.py`                              | `create_leave_request` |
| leave_update | mcp-service `…/tools/leave_write.py`                              | `update_leave_request` |
| leave_cancel | query-service `…/external/hr_leave_client.py`                     | `cancel` |
| leave_cancel | mcp-service `…/tools/leave_write.py`                              | `cancel_leave_request` |
| leave_decide | query-service `…/external/hr_leave_client.py`                     | `decide` |

## Lưu ý

- Đây là hợp đồng HTTP CÓ GATE. Các HTTP nội bộ khác (vd rag-worker `/api/search`,
  `/api/ingest`, ai-router proxy) chưa thuộc gate này — không liệt kê để giữ T1 đúng
  bằng-chứng-code.
- `leave_type` VALUE được test riêng (`test_hr_intents`/registry), không phải gate này.
