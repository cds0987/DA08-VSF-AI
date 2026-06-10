# Hướng dẫn implement Leave Request WRITE flow (cho dev team)

> Mục tiêu: implement luồng **tạo/duyệt đơn nghỉ phép + NATS event** một cách **cẩn thận, KHÔNG phá codebase đang chạy**.
> Bám thiết kế đã chốt: [`docs/api-spec.md`](../../../docs/api-spec.md), [`docs/contracts.md`](../../../docs/contracts.md), [`intent.md`](./intent.md) (section WRITE), [`create_leave_request.md`](../../mcp-service/docs/maintool/create_leave_request.md).
> Trạng thái: 🟡 thiết kế chốt, **chưa code**. Cần SA approve contract trước khi merge.

---

## 0. Nguyên tắc vàng (đọc trước khi gõ dòng nào)

1. **Backward-compatible tuyệt đối.** READ path (`POST /hr/query`, 7 intent) + `GET /health` **không được đổi hành vi**. Mọi test hiện có phải xanh không sửa logic.
2. **Feature-flag OFF mặc định.** Tool write + endpoint write không được tự kích hoạt ở env đang chạy. Bật bằng env mới, mặc định tắt.
3. **NATS là best-effort, KHÔNG fail-closed.** NATS down/lỗi publish **không được** làm sập startup hr-service, không được rollback DB, không được 500 cái write. Ghi DB là source of truth; event là thông báo phụ.
4. **Không đụng migration `0001`/`0002`.** Bảng `leave_requests`/`leave_balance` đã đủ cột → **MVP KHÔNG cần migration mới**. Seed UUID trong 0001 là contract của e2e — không sửa.
5. **Mỗi phase 1 PR, test xanh mới sang phase sau.** Không gộp.

---

## 1. Hai BẪY phá codebase — tránh ngay

### 🪤 Bẫy 1: thêm `@abstractmethod` vào `HrRepository` → vỡ test read
`FakeHrRepository(HrRepository)` ở [tests/test_hr_query_endpoint.py:27](../tests/test_hr_query_endpoint.py#L27) implement **đủ** method abstract hiện tại. Nếu thêm abstract method write → `FakeHrRepository` thành abstract → **không instantiate được → rớt TẤT CẢ test read**.

**Cách an toàn (chọn 1):**
- **(khuyến nghị) Tách interface riêng**: tạo `LeaveWriteRepository(ABC)` mới cho write, `PostgresHrRepository` kế thừa **cả hai**. `HrRepository` (read) giữ NGUYÊN → `FakeHrRepository` không đụng. Test write dùng fake riêng.
- Hoặc thêm method vào `HrRepository` nhưng **đồng thời** cập nhật `FakeHrRepository` trong test + bất kỳ subclass nào (grep `HrRepository)` toàn repo trước).

→ Dù chọn cách nào, **grep `class .*HrRepository` toàn repo** trước khi đổi ABC.

### 🪤 Bẫy 2: tool mcp built-in mặc định BẬT
[mcp_server.py:88-94](../../mcp-service/app/interfaces/mcp_server.py#L88): tool built-in **không khai `enabled` trong config → mặc định BẬT**. Nếu đăng ký `create_leave_request` mà quên thêm section config → nó tự chạy ở env hiện tại + `verify()` connect hr-service → có thể phá.

**Bắt buộc:** thêm section vào `src/mcp-service/config.yaml` với cờ tắt mặc định (xem Phase 3), và `verify()` phải **best-effort** (không raise) — giống `HrQueryTool.verify()`.

---

## 2. Bản đồ file

**ĐỤNG (touch):**
| File | Việc |
|---|---|
| `src/hr-service/app/domain/repositories/` (+ file mới `leave_write_repository.py`) | interface write (Bẫy 1) |
| `src/hr-service/app/domain/entities/dtos.py` | thêm DTO create/result nếu cần |
| `src/hr-service/app/infrastructure/db/postgres_hr_repository.py` | impl write + transaction |
| `src/hr-service/app/api/routes.py` | 3 endpoint write |
| `src/hr-service/app/core/config.py` | `HrSettings` += `nats_url`, `default_approver` |
| `src/hr-service/config.yaml` | env `NATS_URL`, `HR_DEFAULT_APPROVER` |
| `src/hr-service/app/infrastructure/nats_publisher.py` | impl thật (thay stub) |
| `src/hr-service/app/main.py` | lifespan connect/close NATS (best-effort) |
| `src/hr-service/requirements.txt` | `+ nats-py` (pin version) |
| `src/hr-service/tests/` | test write + test publish (fake) |
| `src/mcp-service/app/tools/create_leave_request.py` (mới) | tool proxy |
| `src/mcp-service/app/tools/__init__.py` | import tool mới |
| `src/mcp-service/config.yaml` | section `create_leave_request` (cờ tắt) |

**KHÔNG đụng:** `routes.py` phần `/hr/query` + `_*_summary` read; `hr_query.py` (mcp); migration `0001/0002`; bất kỳ file query-service nào (ngoài role).

---

## 3. Phase 1 — hr-service: endpoint write + repo (CHƯA NATS)

> Mục tiêu phase này: write chạy + test xanh, **chưa** bật NATS (publish gọi vào stub no-op cũ → vô hại).

### 3.1 Config
`HrSettings` (core/config.py) thêm field `default_approver: str = ""` (+ `nats_url` để dành phase 2). `load_settings` đọc `raw.get("default_approver")`. `config.yaml` thêm:
```yaml
default_approver: ${HR_DEFAULT_APPROVER:-}
nats_url: ${NATS_URL:-nats://nats:4222}
```
→ Có default rỗng/sẵn → deploy hiện tại không đổi hành vi.

### 3.2 Repo write (theo Bẫy 1)
Giữ đúng pattern read: **sync SQLAlchemy bọc `asyncio.to_thread`**, session per call, lọc cứng.
- `create_leave_request(user_id, leave_type, start_date, end_date, reason) -> dict`:
  - `days_count = (end - start).days + 1` (ngày lịch).
  - resolve approver: query `EmployeeRecord.manager_user_id` theo `user_id`; `None` → `settings.default_approver`; vẫn rỗng → **raise** (endpoint trả 409/422 rõ ràng).
  - INSERT `LeaveRequestRecord(status='pending', ...)`; commit; return dict đơn.
- `list_pending_approval(approver_user_id) -> list`: `WHERE approver_user_id = :x AND status='pending'`.
- `update_leave_status(request_id, approver_user_id, action, reason=None)`:
  - **1 TRANSACTION**: `SELECT ... FOR UPDATE` đơn; guard `approver_user_id == đơn.approver_user_id AND status=='pending'` (sai → raise → 403/409).
  - approve: set `status='approved'`, `approved_at=now`; trừ `leave_balance` (`annual→annual_leave_used += days`, `sick→sick_leave_used += days`, `personal→bỏ qua`); nếu `used > total` → **raise InsufficientBalance** (rollback, đơn giữ pending) → 409.
  - reject: set `status='rejected'`, `rejected_at=now`, `rejected_reason`.
  - commit.

> ⚠️ Transaction: dùng `with session.begin():` để atomic. KHÔNG để approve thành công mà trừ balance fail (hoặc ngược lại).

### 3.3 Endpoint (routes.py — dùng lại pattern hiện có)
Thêm vào `router` (đã có `Depends(require_internal_token)`), inject repo qua `Depends(get_repo)`:
- `POST /hr/leave-requests` (Pydantic body: user_id, leave_type `Literal["annual","sick","personal"]`, start_date, end_date, reason). Validate `start <= end`. → 201.
- `GET /hr/leave-requests/pending-approval` (query/body `approver_user_id`).
- `POST /hr/leave-requests/{id}/approve` | `.../reject`.
- Map lỗi: guard fail → 403; status không pending → 409; thiếu balance → 409; approver rỗng → 422.

### 3.4 Test phase 1
- Fake write repo (KHÔNG đụng `FakeHrRepository` read).
- Cases: tạo → pending + approver đúng; approve trừ balance đúng; reject set reason; guard sai approver → 403; approve đơn đã approved → 409; thiếu balance → 409; token sai → 401.

✅ **Regression bắt buộc:** `pytest src/hr-service` — tất cả test read cũ vẫn xanh.

---

## 4. Phase 2 — NATS publisher thật (best-effort)

### 4.1 Dependency
`requirements.txt` += `nats-py==<pin>`. Rebuild Docker, verify import.

### 4.2 NatsPublisher thật (thay stub, GIỮ interface `Publisher`)
Giữ nguyên chữ ký `async def publish(self, subject, payload) -> None` + `async def aclose()` (để `EmployeeProfileService` và code khác không vỡ).
- Connect lazy hoặc ở lifespan; JetStream publish; `event_id=uuid4`, `occurred_at=now ISO`.
- **Best-effort:** mọi lỗi connect/publish → `logger.warning` + return (KHÔNG raise). Bọc try/except toàn bộ.

### 4.3 Lifecycle (main.py)
Thêm `lifespan`: startup → tạo `NatsPublisher`, thử connect (lỗi → log, vẫn chạy); lưu `app.state.publisher`. shutdown → `aclose()`. Inject vào routes qua `Depends`.

### 4.4 Publish trong endpoint — SAU COMMIT
Trong `POST /leave-requests`, `approve`, `reject`: **sau khi repo commit thành công** mới `await publisher.publish(subject, payload)`. Publish lỗi không ảnh hưởng response (đã best-effort).
- Subject + payload đúng [contract](../../../docs/contracts.md): `hr.leave_request.created|approved|rejected`, kèm `requester_user_id` + `approver_user_id`.

### 4.5 Test phase 2
- Fake publisher ghi lại call → assert đúng subject + payload sau write.
- Test publish raise → endpoint **vẫn** trả 200/201 (best-effort).

> ❗ Không bật `TOOL_HR_QUERY_ENABLED`/đụng `hr.employee_profile.updated` scaffold — để nguyên, chỉ thêm leave event.

---

## 5. Phase 3 — mcp-service: tool `create_leave_request`

### 5.1 Tool (theo đúng pattern `hr_query.py`)
File mới `app/tools/create_leave_request.py`:
- Class theo khuôn `HrQueryTool`: `__init__` đọc `params` lồng (`hr_service_url`, `internal_token`), `_get_client()` httpx, `register(mcp)` với `@mcp.tool()`, `verify()` **best-effort** (không raise), `aclose()`.
- `@mcp.tool() async def create_leave_request(user_id, leave_type, start_date, end_date, reason="")` → proxy `POST /hr/leave-requests` (header `X-Internal-Token`) → trả body.
- `user_id` inject từ client (không tin LLM).
- `register_tool("create_leave_request", lambda s,p: CreateLeaveRequestTool(s,p))` cuối file.

### 5.2 Đăng ký + cờ tắt (Bẫy 2)
- `app/tools/__init__.py` += `from app.tools import create_leave_request  # noqa: F401`.
- `config.yaml` thêm (BẮT BUỘC, nếu không tool tự bật):
```yaml
create_leave_request:
  enabled: ${TOOL_CREATE_LEAVE_REQUEST_ENABLED:-0}
  params:
    hr_service_url: ${HR_SERVICE_URL:-http://hr-service:8004}
    internal_token: ${HR_SERVICE_INTERNAL_TOKEN:-}
```
→ ⚠️ Sau khi sửa `mcp-service/config.yaml`, **chạy CI config parity check** (xem CLAUDE/memory: thêm key config có thể fail `extra_forbidden` ở `config_schema.py`). Nếu có schema → thêm field cùng lượt.

### 5.3 Test phase 3
- Mock httpx → assert proxy đúng path/body, `user_id` truyền đúng.
- `verify()` khi hr-service down → KHÔNG raise (best-effort), không phá `rag_search` fail-closed.
- `pytest src/mcp-service` xanh.

---

## 6. Phase 4 — e2e + bàn giao

- Mở rộng `src/hr-service/scripts/e2e_hr_integration.py`: thêm chain `create_leave_request` (mcp→hr→Postgres) + approve qua HTTP → assert status đổi + balance trừ.
- Ghi/chốt contract event ở `docs/contracts.md` (đã có) → **báo người ôm query-service** thêm subscriber (giống `notify_subscriber` cho `doc_new`) — ngoài role mình.

---

## 7. Checklist "không phá vỡ" (chạy trước mỗi PR)

- [ ] `pytest src/hr-service` xanh (test read cũ KHÔNG sửa).
- [ ] `pytest src/mcp-service` xanh; `rag_search` vẫn fail-closed.
- [ ] Tool write **mặc định TẮT** (`TOOL_CREATE_LEAVE_REQUEST_ENABLED=0`); env hiện tại không thấy tool mới.
- [ ] NATS down → hr-service vẫn start, write vẫn 200, chỉ log warning.
- [ ] `POST /hr/query` + `GET /health` byte-for-byte như cũ.
- [ ] Không có migration mới; seed 0001 nguyên vẹn.
- [ ] grep `class .*HrRepository` — mọi subclass đã implement đủ (không vỡ ABC).
- [ ] CI config parity (mcp) xanh sau khi sửa `config.yaml`.

## 8. Thứ tự PR

1. **PR1 (hr-service write, no NATS):** Phase 1 + 3.4. Publish gọi stub no-op cũ (vô hại).
2. **PR2 (NATS publisher):** Phase 2. Best-effort, có test fake publisher.
3. **PR3 (mcp tool):** Phase 3, cờ tắt mặc định.
4. **PR4 (e2e + handoff):** Phase 4.

## 9. Rollback

- Mỗi feature sau cờ env: gỡ `TOOL_CREATE_LEAVE_REQUEST_ENABLED` → tool biến mất, không cần revert code.
- Endpoint write: chưa ai gọi (chỉ mcp tool đã tắt + UI chưa có) → để đó vô hại.
- NATS: publish best-effort → tắt `NATS_URL`/để trống → publisher no-op, write vẫn chạy.
- Không có migration → không cần downgrade DB.
