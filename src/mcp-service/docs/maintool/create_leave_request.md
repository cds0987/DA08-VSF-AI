# Tool `create_leave_request` (WRITE)

> Trạng thái: 🟡 **THIẾT KẾ ĐÃ CHỐT, chưa implement** (cần SA approve contract).
> Đây là tool **WRITE** — tách hẳn khỏi [`hr_query`](./hr_query.md) (READ). hr_query chỉ đọc; tool này ghi đơn nghỉ phép.
> Đồng bộ với [`docs/api-spec.md`](../../../../docs/api-spec.md) + [`docs/contracts.md`](../../../../docs/contracts.md) + [`src/hr-service/docs/intent.md`](../../../hr-service/docs/intent.md) (section WRITE flow).
> 🛠️ **Hướng dẫn implement cẩn thận (không phá codebase):** [`src/hr-service/docs/leave-request-write-implementation.md`](../../../hr-service/docs/leave-request-write-implementation.md).

---

## Scope

| | hr_query (READ) | create_leave_request (WRITE) |
|---|---|---|
| Bản chất | đọc data HR cá nhân | tạo đơn nghỉ phép |
| Số tool MCP | 1 | 1 |
| approve/reject | — | **KHÔNG** phải MCP tool (HTTP nội bộ, xem dưới) |

`create_leave_request` là **MCP tool duy nhất** cho luồng write. Duyệt/từ chối đơn **không** expose qua MCP — đó là HTTP nội bộ `X-Internal-Token` do phía UI/sếp gọi thẳng hr-service.

## Chữ ký tool (dự kiến)

```python
create_leave_request(
    user_id: str,          # MCP client (query-service) inject từ JWT — KHÔNG để LLM tự điền
    leave_type: Literal["annual", "sick", "personal"],
    start_date: str,       # 'YYYY-MM-DD'
    end_date: str,         # 'YYYY-MM-DD'
    reason: str = "",
) -> dict                  # { id, status: "pending", approver_user_id, days_count }
```

- mcp-service **proxy** sang hr-service `POST /hr/leave-requests` (header `X-Internal-Token`), trả thẳng body.
- `user_id` là tham số nhạy cảm — client inject, **không tin LLM** (giống `document_ids`/`user_id` của các tool khác).

## Boundary (bất biến)

- **Confirmation gate ở query-service, KHÔNG ở mcp/hr:** AI trích xuất field → hiển thị draft → user xác nhận → query-service mới gọi tool (draft lưu Redis `pending_action:{user_id}` TTL ~10'). mcp/hr **không** giả định đã confirm — chỉ ghi khi được gọi.
- **mcp-service chỉ proxy**, không validate nghiệp vụ. Validate + resolve approver + transaction là việc hr-service.
- Tham số nhạy cảm `user_id` do client inject từ JWT.

## hr-service làm gì khi nhận (tóm tắt — chi tiết ở intent.md)

1. `days_count = end - start + 1` (ngày lịch, server tính).
2. `approver_user_id = employees.manager_user_id` **OR** `HR_DEFAULT_APPROVER`.
3. INSERT `status='pending'` → commit → publish NATS `hr.leave_request.created`.

## Luồng duyệt (ngoài MCP)

```
(UI/sếp) ──POST /hr/leave-requests/{id}/approve|reject (X-Internal-Token)──► hr-service
              guard: đơn.approver_user_id == current AND status='pending' (KHÔNG dùng app-role)
              approve: TRANSACTION update + trừ leave_balance → publish hr.leave_request.approved
              reject:  update + rejected_reason → publish hr.leave_request.rejected
```

Báo tới user (sếp/nhân viên) do **query-service Notification Center** consume NATS event → SSE. hr-service **chỉ publish**, không đẩy thẳng tới user. (Contract event: xem `docs/contracts.md` / `api-spec.md`.)

## Việc phải làm khi implement

- **mcp-service:** đăng ký tool `create_leave_request` ở `app/tools/`, proxy POST `/hr/leave-requests`, inject `user_id`. Tests proxy.
- **hr-service:** 3 endpoint write + repo write (`create_leave_request`, `list_pending_approval`, `update_leave_status`) + transaction trừ balance + `NatsPublisher` thật + publish 3 event.
- **query-service (ngoài role):** confirmation flow + subscriber NATS → SSE.
