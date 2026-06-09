# Kế hoạch chuyển đổi HR từ mcp-service sang hr-service

> Trạng thái hiện tại: đã triển khai `hr-service` độc lập và `mcp-service` gọi qua HTTP proxy. Tài liệu này giữ lại để trace quyết định và đối chiếu schema.

> Đối chiếu giữa code thực tế trong `src/mcp-service/` và tài liệu thiết kế (`docs/architecture.md`, `docs/api-spec.md`, `docs/data-schema.md`, `src/mcp-service/docs/refactor/hr-service-split.md`).

---

## Hiện trạng code (mcp-service)

### Những gì đang tồn tại trong mcp-service

| File | Vai trò hiện tại |
|---|---|
| `app/tools/hr_query.py` | HrQueryTool: kết nối thẳng Postgres, xử lý 4 intent, chứa summary builders |
| `app/domain/repositories/hr_repository.py` | ABC `HrRepository` với 5 method (`ping`, `get_leave_balance`, `get_leave_requests`, `get_attendance`, `get_onboarding`, `get_payroll`) |
| `app/domain/entities/tool_io.py` | Toàn bộ DTO HR + `RagSearchInput` dùng chung |
| `app/infrastructure/db/models.py` | 5 ORM model: `LeaveBalanceRecord`, `LeaveRequestRecord`, `AttendanceRecord`, `OnboardingRecord`, `PayrollSummaryRecord` (schema `hr_mock`) |
| `app/infrastructure/db/postgres_hr_repository.py` | `PostgresHrRepository` — sync SQLAlchemy + `asyncio.to_thread` |
| `migrations/versions/0001_create_hr_schema.py` | Tạo schema `hr_mock` + 5 bảng + seed 2 user mẫu |
| `migrations/env.py` | Alembic env — import `Base` từ `app.infrastructure.db.models` |
| `config.yaml` → `hr_query.params.database_url` | Đọc `${MCP_DATABASE_URL}` — kết nối thẳng Postgres |

### Vấn đề coupling hiện tại

1. mcp-service giữ SQLAlchemy engine + connection pool + Alembic cho dữ liệu HR — không liên quan nhiệm vụ chính (route MCP tool).
2. `app/domain/entities/tool_io.py` trộn lẫn `RagSearchInput` (rag_search tool) với toàn bộ DTO HR — không thể xóa file mà không ảnh hưởng tool khác.
3. `migrations/env.py` import từ `app.infrastructure.db.models` — buộc mcp-service phải giữ models HR dù không cần.

---

## Đối chiếu schema: hr_mock (hiện tại) vs hr_svc (mục tiêu)

### Bảng có trong hr_mock nhưng KHÔNG có trong data-schema.md `hr_svc`

| Bảng | Ghi chú |
|---|---|
| `hr_mock.attendance` | Mock-only. Cần định nghĩa lại trong hr-service với schema chuẩn |
| `hr_mock.onboarding` | Mock-only. Cần định nghĩa lại trong hr-service |

### Bảng có trong hr_svc nhưng KHÔNG có trong hr_mock

| Bảng | Ghi chú |
|---|---|
| `hr_svc.departments` | data-schema.md có, hr_mock chưa |
| `hr_svc.employees` | data-schema.md có (`user_id`, `manager_user_id`, `employment_status`...), hr_mock chưa |

### Bảng có ở cả hai nhưng schema khác nhau

| Bảng | Sự khác biệt |
|---|---|
| `leave_requests` | hr_mock: `(id, user_id, leave_type, start_date, end_date, days_count, status, reason, created_at)` — đơn giản hóa. hr_svc: thêm `employee_id`, `approver_user_id`, `approved_at`, `rejected_at`, `rejected_reason`, `updated_at` |
| `payroll_summary` | hr_mock: `gross_salary`/`deductions`/`net_salary` kiểu `float`. hr_svc: kiểu `NUMERIC(12,2)` |

**Hành động:** Migration mới trong hr-service phải tạo schema `hr_svc` với đầy đủ columns theo data-schema.md — không copy nguyên migration cũ.

---

## Những gì CHUYỂN sang hr-service

### 1. Domain — toàn bộ di chuyển

| Nguồn (mcp-service) | Đích (hr-service) | Thay đổi |
|---|---|---|
| `app/domain/repositories/hr_repository.py` | `app/domain/repositories/hr_repository.py` | Giữ nguyên ABC — không sửa interface |

### 2. DTOs — tách khỏi tool_io.py

Các class sau di chuyển từ `app/domain/entities/tool_io.py` sang `app/domain/entities/dtos.py` trong hr-service:

- `HrQueryInput`
- `LeaveBalanceDTO`
- `LeaveRequestDTO`
- `PayrollDTO`
- `AttendanceDTO`
- `OnboardingItemDTO`
- `OnboardingDTO`
- `HrQueryResult`

`RagSearchInput` **giữ nguyên** trong `mcp-service/app/domain/entities/tool_io.py` (dùng bởi rag_search tool).

### 3. Infrastructure — di chuyển và đổi schema

| Nguồn (mcp-service) | Đích (hr-service) | Thay đổi |
|---|---|---|
| `app/infrastructure/db/models.py` | `app/infrastructure/db/models.py` | Đổi `schema="hr_mock"` → `schema="hr_svc"`. Bổ sung model `EmployeeRecord`, `DepartmentRecord` theo data-schema.md. Cập nhật `LeaveRequestRecord` thêm `approver_user_id`, `approved_at`, v.v. |
| `app/infrastructure/db/postgres_hr_repository.py` | `app/infrastructure/db/postgres_hr_repository.py` | Đổi import DTO từ `app.domain.entities.dtos`. Giữ logic query — LUÔN filter `WHERE user_id`. |

### 4. Summary builders — chuyển vào routes

Các hàm sau trong `mcp-service/app/tools/hr_query.py` chuyển sang `hr-service/app/interfaces/api/routes.py`:

- `_leave_balance_summary(annual_remaining, sick_remaining) -> str`
- `_leave_requests_summary(requests) -> str`
- `_attendance_summary(work_days, late_count, absent_count) -> str`
- `_onboarding_summary(status, completed, total) -> str`

### 5. Migrations — di chuyển toàn bộ thư mục

| Nguồn (mcp-service) | Đích (hr-service) |
|---|---|
| `migrations/versions/0001_create_hr_schema.py` | `migrations/versions/0001_create_hr_schema.py` — **viết lại** theo hr_svc (không copy nguyên, xem phần schema diff bên trên) |
| `migrations/env.py` | `migrations/env.py` — sửa import: `from app.infrastructure.db.models import Base` |
| `migrations/script.py.mako` | `migrations/script.py.mako` — copy nguyên |
| `alembic.ini` | `alembic.ini` — copy, sửa `script_location` trỏ vào `migrations/` của hr-service |

---

## Những gì BỊ XÓA khỏi mcp-service

| File/Folder | Hành động |
|---|---|
| `app/domain/repositories/hr_repository.py` | Xóa cả file |
| `app/infrastructure/db/models.py` | Xóa cả file |
| `app/infrastructure/db/postgres_hr_repository.py` | Xóa cả file |
| `app/infrastructure/db/__init__.py` | Xóa nếu thư mục `db/` rỗng sau khi xóa 2 file trên |
| `migrations/` (cả thư mục) | Move sang hr-service rồi xóa |
| `alembic.ini` | Move sang hr-service rồi xóa |
| Các DTO HR trong `tool_io.py` | Xóa phần HR, giữ `RagSearchInput` |
| `requirements.txt`: `sqlalchemy`, `psycopg2-binary`, `alembic` | Xóa nếu không còn dùng ở nơi khác trong mcp-service |

---

## Những gì THAY ĐỔI trong mcp-service

### `app/tools/hr_query.py` → HTTP proxy

Toàn bộ logic DB + summary builders bị thay bằng HTTP call đến hr-service:

```python
import httpx
from app.tools.base import register_tool

class HrQueryTool:
    name = "hr_query"

    def __init__(self, settings, params):
        nested = dict(params.get("params") or {})
        self._url = str(nested.get("hr_service_url") or "").rstrip("/")
        self._token = str(nested.get("internal_token") or "")
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict:
        return {"X-Internal-Token": self._token} if self._token else {}

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._url, timeout=10.0)
        return self._client

    def register(self, mcp) -> None:
        @mcp.tool()
        async def hr_query(user_id: str, intent: str) -> dict:
            """Read current user's HR data. user_id injected from JWT."""
            resp = await self._get_client().post(
                "/hr/query",
                json={"user_id": user_id, "intent": intent},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def verify(self) -> None:
        resp = await self._get_client().get("/health", headers=self._headers())
        resp.raise_for_status()

    async def aclose(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

register_tool("hr_query", lambda settings, params: HrQueryTool(settings, params))
```

### `config.yaml` → đổi params

**Xóa:**
```yaml
hr_query:
  params:
    database_url: ${MCP_DATABASE_URL:-}   # ← xóa
```

**Thay bằng:**
```yaml
hr_query:
  enabled: ${TOOL_HR_QUERY_ENABLED:-0}
  params:
    hr_service_url: ${HR_SERVICE_URL:-http://hr-service:8004}
    internal_token: ${HR_SERVICE_INTERNAL_TOKEN:-}
```

`MCP_DATABASE_URL` bị xóa khỏi mcp-service hoàn toàn.

---

## Những gì MỚI trong hr-service

### Thêm mới (không có trong mcp-service)

| File | Nội dung |
|---|---|
| `app/api/auth.py` | Verify `X-Internal-Token` — constant-time compare |
| `app/api/routes.py` | `POST /hr/query`, `GET /health` + summary builders chuyển từ mcp-service |
| `app/core/config.py` | `HrSettings`: `database_url`, `host`, `port`, `internal_token` |
| `app/main.py` | FastAPI app :8004 |
| `app/application/services/employee_profile_service.py` | Publish NATS event `hr.employee_profile.updated` khi employee profile thay đổi |
| `app/infrastructure/nats_publisher.py` | NATS publisher |
| `Dockerfile` | |
| `config.yaml` | `HrSettings` fields |
| `requirements.txt` | `fastapi`, `uvicorn`, `sqlalchemy`, `psycopg2-binary`, `alembic`, `nats-py` |

### `POST /hr/query` — endpoint chính

```
Header: X-Internal-Token: <shared secret>
Body:   { "user_id": "...", "intent": "leave_balance" | "leave_requests" | "attendance" | "onboarding" }

Response 200:
{
  "intent": "leave_balance",
  "data": { "annual_total": 12, "annual_used": 3, "annual_remaining": 9, ... },
  "summary": "Bạn còn 9 ngày phép năm và 10 ngày phép ốm."
}
```

---

## Thứ tự thực hiện

```
[1]  Tạo scaffold src/hr-service/ + Dockerfile + config.yaml + requirements.txt
[2]  Move migrations/ + alembic.ini từ mcp-service → hr-service
[3]  Viết lại migration 0001 theo schema hr_svc (đổi schema name, bổ sung columns)
[4]  Move + sửa models.py (hr_mock → hr_svc, thêm EmployeeRecord / DepartmentRecord)
[5]  Move hr_repository.py (ABC) vào hr-service/app/domain/repositories/
[6]  Tách DTOs HR ra dtos.py trong hr-service; xóa phần HR khỏi mcp-service/tool_io.py
[7]  Move + sửa postgres_hr_repository.py (đổi import DTO)
[8]  Viết app/api/auth.py + app/api/routes.py (chuyển summary builders vào đây)
[9]  Viết app/core/config.py (HrSettings) + app/main.py
[10] Viết app/application/services/employee_profile_service.py + nats_publisher.py
[11] Test hr-service độc lập: pytest + curl thủ công /hr/query + /health
[12] Sửa mcp-service/app/tools/hr_query.py → HTTP proxy (code ở trên)
[13] Cập nhật mcp-service/config.yaml (đổi params, xóa MCP_DATABASE_URL)
[14] Xóa các file HR không còn dùng trong mcp-service (xem bảng "bị xóa" ở trên)
[15] Cập nhật mcp-service tests: mock httpx thay vì mock PostgresHrRepository
[16] Chạy tích hợp: mcp-service + hr-service cùng lúc, kiểm verify() startup
```

---

## SA Blockers chặn các bước cụ thể

| # | Trạng thái | Chặn bước |
|---|---|---|
| SA-3: JWT claim gate intent nhạy cảm (`payroll`, `performance`) | ⚠️ OPEN | Bước [8] khi mở Giai đoạn 2 |
| SA-4: Reserved-param contract `user_id`/`document_ids` trong `_inject_reserved` | ⚠️ OPEN | Bước [15] phía query-service |

SA-1 (DB instance) và SA-2 (nguồn employee_profile) đã RESOLVED — xem `src/mcp-service/docs/maintool/hr_query.md`.

---

## Không làm trong migration này

- Không đổi output contract `{ intent, data, summary }` — query-service không cần sửa gì.
- Không thêm intent mới — scope chỉ là tách hạ tầng.
- Không thay DB mock bằng HRIS thật — đó là Giai đoạn 2 riêng.
- Không expose HR Service ra ngoài internet — internal only, xác thực bằng `X-Internal-Token`.

---

## Hướng dẫn dev — Thực hiện an toàn, không phá codebase hai bên

### Nguyên tắc cốt lõi

**`TOOL_HR_QUERY_ENABLED=0` là lưới an toàn chính.**
Config mcp-service mặc định `enabled: ${TOOL_HR_QUERY_ENABLED:-0}`. Tool bị tắt hoàn toàn — mcp-service không instantiate `HrQueryTool`, không kết nối DB, không chạy `verify()`. Điều này cho phép dev **xây hr-service và sửa mcp-service proxy trên cùng một nhánh mà không ảnh hưởng môi trường đang chạy**, miễn là không set `TOOL_HR_QUERY_ENABLED=1` trước khi sẵn sàng.

**Quy tắc làm việc:**
1. Không sửa mcp-service và hr-service trong cùng một commit — tách thành PR riêng hoặc commit riêng để dễ rollback.
2. Không xóa file cũ trong mcp-service cho đến khi integration test giữa hai service pass.
3. Không đổi output contract `{ intent, data, summary }` — đây là điểm neo duy nhất giữ query-service không phải sửa.
4. Luôn chạy `pytest src/mcp-service` sau mỗi bước sửa mcp-service, dù chỉ đổi import.

---

### Phase 0 — Chuẩn bị (không chạm code)

**Mục tiêu:** đảm bảo baseline xanh trước khi bắt đầu.

```bash
# 1. Xác nhận tool đang bị tắt (không có rủi ro production)
grep "TOOL_HR_QUERY_ENABLED" src/mcp-service/config.yaml
# expected: enabled: ${TOOL_HR_QUERY_ENABLED:-0}

# 2. Chạy test hiện tại — phải xanh hoàn toàn trước khi bắt đầu
pytest src/mcp-service -q
# Nếu đỏ ở đây → fix trước, không tiếp tục

# 3. Tạo feature branch
git checkout -b feat/hr-service-extract
```

**Checkpoint:** `pytest src/mcp-service` xanh. Không có gì thay đổi.

---

### Phase 1 — Xây hr-service độc lập (không chạm mcp-service)

**Mục tiêu:** hr-service chạy và trả đúng contract — mcp-service không biết hr-service tồn tại.

#### Bước 1: Scaffold cấu trúc thư mục

```
src/hr-service/
├── app/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   └── routes.py
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── entities/
│   │   │   ├── __init__.py
│   │   │   └── dtos.py
│   │   └── repositories/
│   │       ├── __init__.py
│   │       └── hr_repository.py
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   └── db/
│   │       ├── __init__.py
│   │       ├── models.py
│   │       └── postgres_hr_repository.py
│   └── main.py
├── migrations/
│   ├── __init__.py
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── __init__.py
│       └── 0001_create_hr_schema.py
├── tests/
│   ├── __init__.py
│   └── test_hr_query_endpoint.py
├── alembic.ini
├── config.yaml
├── Dockerfile
└── requirements.txt
```

Chỉ tạo thư mục và file rỗng (`__init__.py`) ở bước này. Commit: `chore(hr-service): scaffold folder structure`.

#### Bước 2: Copy + sửa domain layer

**`app/domain/entities/dtos.py`** — copy từ `mcp-service/app/domain/entities/tool_io.py`, bỏ `RagSearchInput`, đổi import:

```python
# hr-service/app/domain/entities/dtos.py
# Nguồn gốc: mcp-service/app/domain/entities/tool_io.py — phần HR
# RagSearchInput KHÔNG copy sang đây (thuộc mcp-service)
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class HrQueryInput:
    user_id: str
    intent: str

@dataclass
class LeaveBalanceDTO:
    annual_total: int
    annual_used: int
    annual_remaining: int
    sick_total: int
    sick_used: int
    sick_remaining: int

# ... (copy các DTO còn lại từ tool_io.py)
```

**`app/domain/repositories/hr_repository.py`** — copy nguyên từ mcp-service, chỉ đổi import:

```python
# Đổi dòng import từ:
from app.domain.entities.tool_io import (AttendanceDTO, ...)
# Thành:
from app.domain.entities.dtos import (AttendanceDTO, ...)
```

> **Lưu ý quan trọng:** KHÔNG xóa `HrRepository` trong mcp-service ở bước này. Cả hai bản cùng tồn tại.

**Checkpoint:** `pytest src/mcp-service` vẫn xanh (chưa chạm mcp-service).

#### Bước 3: Copy + sửa infrastructure layer

**`app/infrastructure/db/models.py`** — copy từ mcp-service, đổi schema và bổ sung columns còn thiếu:

```python
# Đổi schema ở mọi model:
__table_args__ = {"schema": "hr_mock"}   # ← cũ
__table_args__ = {"schema": "hr_svc"}    # ← mới

# LeaveRequestRecord — thêm các columns còn thiếu so với data-schema.md:
approver_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
approved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
rejected_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

# Thêm model mới:
class DepartmentRecord(Base):
    __tablename__ = "departments"
    __table_args__ = {"schema": "hr_svc"}
    # ... theo data-schema.md

class EmployeeRecord(Base):
    __tablename__ = "employees"
    __table_args__ = {"schema": "hr_svc"}
    # ... theo data-schema.md
```

**`app/infrastructure/db/postgres_hr_repository.py`** — copy từ mcp-service, chỉ đổi import:

```python
# Đổi:
from app.domain.entities.tool_io import (...)
# Thành:
from app.domain.entities.dtos import (...)

from app.infrastructure.db.models import (...)   # đường dẫn giữ nguyên, module mới
```

> **Lưu ý:** mcp-service vẫn có bản gốc của tất cả các file này. Không xóa gì ở mcp-service.

**Checkpoint:** `pytest src/mcp-service` xanh.

#### Bước 4: Viết migration mới

**`migrations/versions/0001_create_hr_schema.py`** — **viết lại hoàn toàn**, KHÔNG copy từ mcp-service vì schema đã đổi:

```python
# Tên schema: hr_svc (không phải hr_mock)
# Thêm: departments, employees, columns mới trong leave_requests
# Giữ: leave_balance, attendance, onboarding, payroll_summary
op.execute("CREATE SCHEMA IF NOT EXISTS hr_svc")
```

**`migrations/env.py`** — copy từ mcp-service, đổi import:

```python
# Đổi:
from app.infrastructure.db.models import Base
# thành đường dẫn hr-service — nhưng module name giữ nguyên nên không cần đổi
# chỉ cần đảm bảo PYTHONPATH trỏ đúng src/hr-service khi chạy alembic
```

**`alembic.ini`** — copy từ mcp-service, giữ nguyên cấu trúc. Khi chạy migration:

```bash
# Phải cd vào thư mục hr-service hoặc dùng -c:
DATABASE_URL=postgresql://... alembic -c src/hr-service/alembic.ini upgrade head
```

**Checkpoint:** `alembic upgrade head` chạy được trên DB test, `alembic downgrade base` rollback sạch.

#### Bước 5: Viết API layer

**`app/api/auth.py`** — verify `X-Internal-Token`:

```python
import hmac
from fastapi import Header, HTTPException

def verify_internal_token(expected: str, x_internal_token: str = Header("")) -> None:
    if not expected:
        return   # token trống = auth tắt (dev mode)
    if not hmac.compare_digest(expected.encode(), x_internal_token.encode()):
        raise HTTPException(status_code=401, detail="Invalid internal token")
```

**`app/api/routes.py`** — chuyển summary builders từ mcp-service vào đây, viết handler:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.domain.repositories.hr_repository import HrRepository

router = APIRouter()

# ── summary builders (chuyển từ mcp-service/app/tools/hr_query.py) ──────────

def _leave_balance_summary(annual_remaining: int, sick_remaining: int) -> str:
    return f"Bạn còn {annual_remaining} ngày phép năm và {sick_remaining} ngày phép ốm."

def _leave_requests_summary(requests: list) -> str:
    if not requests:
        return "Bạn chưa có đơn nghỉ phép nào."
    r = requests[0]
    return f"Đơn nghỉ gần nhất là {r['leave_type']} từ {r['start_date']} đến {r['end_date']}, trạng thái {r['status']}."

def _attendance_summary(work_days: int, late_count: int, absent_count: int) -> str:
    return f"Tháng này bạn có {work_days} ngày công, đi muộn {late_count} lần và vắng {absent_count} ngày."

def _onboarding_summary(status: str, completed: int, total: int) -> str:
    return f"Trạng thái onboarding: {status}, đã hoàn thành {completed}/{total} mục."

# ── endpoint ─────────────────────────────────────────────────────────────────

class HrQueryRequest(BaseModel):
    user_id: str
    intent: str

@router.post("/hr/query")
async def hr_query(body: HrQueryRequest, repo: HrRepository = Depends(get_repo)):
    if body.intent == "leave_balance":
        dto = await repo.get_leave_balance(body.user_id)
        if dto is None:
            raise HTTPException(404, "no HR data for this user")
        data = {
            "annual_total": dto.annual_total, "annual_used": dto.annual_used,
            "annual_remaining": dto.annual_remaining,
            "sick_total": dto.sick_total, "sick_used": dto.sick_used,
            "sick_remaining": dto.sick_remaining,
        }
        return {"intent": body.intent, "data": data,
                "summary": _leave_balance_summary(dto.annual_remaining, dto.sick_remaining)}
    # ... các intent khác giữ cùng pattern

@router.get("/health")
async def health():
    return {"status": "ok"}
```

**`app/core/config.py`** — HrSettings:

```python
from pydantic_settings import BaseSettings

class HrSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8004
    log_level: str = "INFO"
    database_url: str
    internal_token: str = ""

    class Config:
        env_prefix = "HR_"
```

#### Bước 6: Test hr-service độc lập

```python
# tests/test_hr_query_endpoint.py
# Dùng httpx.AsyncClient + FakeRepo inject qua FastAPI override_dependencies
# KHÔNG kết nối Postgres thật trong unit test

from fastapi.testclient import TestClient
from app.main import app
from app.api.routes import get_repo

def test_leave_balance_endpoint(fake_repo):
    app.dependency_overrides[get_repo] = lambda: fake_repo
    client = TestClient(app)
    resp = client.post("/hr/query",
                       json={"user_id": USER_HR, "intent": "leave_balance"},
                       headers={"X-Internal-Token": "test-token"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "leave_balance"
    assert set(body.keys()) == {"intent", "data", "summary"}

def test_cross_user_isolation(fake_repo):
    # user A không thấy data user B
    app.dependency_overrides[get_repo] = lambda: fake_repo
    client = TestClient(app)
    r1 = client.post("/hr/query", json={"user_id": USER_HR, "intent": "leave_balance"},
                     headers={"X-Internal-Token": "test-token"})
    r2 = client.post("/hr/query", json={"user_id": USER_FINANCE, "intent": "leave_balance"},
                     headers={"X-Internal-Token": "test-token"})
    assert r1.json()["data"] != r2.json()["data"]

def test_invalid_token_rejected():
    client = TestClient(app)
    resp = client.post("/hr/query",
                       json={"user_id": USER_HR, "intent": "leave_balance"},
                       headers={"X-Internal-Token": "wrong"})
    assert resp.status_code == 401

def test_health():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
```

```bash
# Chạy test hr-service
pytest src/hr-service -q

# Đồng thời xác nhận mcp-service vẫn xanh
pytest src/mcp-service -q
```

**Checkpoint Phase 1:** `pytest src/hr-service` xanh, `pytest src/mcp-service` xanh, hr-service chạy được `uvicorn app.main:app` độc lập.

---

### Phase 2 — Chuyển mcp-service sang HTTP proxy

**Mục tiêu:** mcp-service gọi hr-service qua HTTP thay vì trực tiếp vào DB. `TOOL_HR_QUERY_ENABLED` vẫn là `0` trong suốt phase này.

#### Bước 7: Sửa `app/tools/hr_query.py` → HTTP proxy

Thay toàn bộ nội dung file bằng phiên bản proxy (xem mục "Những gì THAY ĐỔI trong mcp-service" bên trên). Các điểm cần chú ý:

- **Xóa** `_build_hr_repository`, toàn bộ `import` liên quan DB, tất cả summary builders.
- **Giữ** nguyên: `class HrQueryTool`, `name = "hr_query"`, `register_tool(...)` ở cuối file.
- `verify()` bây giờ gọi `GET /health` của hr-service thay vì `repo.ping()`.
- Không import gì từ `app.domain.repositories.hr_repository` hay `app.infrastructure.db`.

```bash
# Sau khi sửa, chạy ngay:
pytest src/mcp-service -q
# DỰ ĐOÁN: test_hr_query_tool.py SẼ ĐỎ — bình thường, xử lý ở bước tiếp theo
```

#### Bước 8: Cập nhật test mcp-service

`tests/test_hr_query_tool.py` hiện dùng `FakeHrRepository` + `monkeypatch._build_hr_repository`. Sau khi tool trở thành HTTP proxy, phải đổi sang mock `httpx`:

```python
# tests/test_hr_query_tool.py — sau khi proxy
import pytest
import httpx
from respx import MockRouter   # pip install respx

USER_HR = "11111111-1111-4111-8111-111111111111"
BASE_URL = "http://hr-service:8004"

FAKE_RESPONSES = {
    "leave_balance": {
        "intent": "leave_balance",
        "data": {"annual_total": 12, "annual_used": 4, "annual_remaining": 8,
                 "sick_total": 10, "sick_used": 1, "sick_remaining": 9},
        "summary": "Bạn còn 8 ngày phép năm và 9 ngày phép ốm.",
    },
    "attendance": {
        "intent": "attendance",
        "data": {"period": "2026-06", "work_days": 20, "late_count": 1, "absent_count": 0},
        "summary": "Tháng này bạn có 20 ngày công, đi muộn 1 lần và vắng 0 ngày.",
    },
    # ... các intent khác
}

@pytest.fixture
def proxy_tool():
    from app.tools.hr_query import HrQueryTool
    from app.core.config import McpSettings
    settings = McpSettings(...)   # giữ nguyên như cũ
    tool = HrQueryTool(settings, {"params": {
        "hr_service_url": BASE_URL,
        "internal_token": "test-token",
    }})
    from tests.helpers import FakeMCP
    mcp = FakeMCP()
    tool.register(mcp)
    return mcp.tools["hr_query"], tool

@pytest.mark.asyncio
async def test_leave_balance_proxied(proxy_tool, respx_mock):
    fn, _ = proxy_tool
    respx_mock.post(f"{BASE_URL}/hr/query").mock(
        return_value=httpx.Response(200, json=FAKE_RESPONSES["leave_balance"])
    )
    result = await fn(USER_HR, "leave_balance")
    assert result["intent"] == "leave_balance"
    assert result["data"]["annual_remaining"] == 8
    assert set(result.keys()) == {"intent", "data", "summary"}

@pytest.mark.asyncio
async def test_hr_service_down_raises(proxy_tool, respx_mock):
    fn, _ = proxy_tool
    respx_mock.post(f"{BASE_URL}/hr/query").mock(
        return_value=httpx.Response(503)
    )
    with pytest.raises(httpx.HTTPStatusError):
        await fn(USER_HR, "leave_balance")
```

> **Tại sao dùng `respx` thay vì `unittest.mock`?** `respx` mock ở tầng transport của `httpx` — đảm bảo không có request thật nào ra ngoài trong test, kể cả khi code thay đổi cách tạo client.

```bash
# Thêm respx vào mcp-service requirements (test dependency):
echo "respx" >> src/mcp-service/requirements-dev.txt

# Chạy lại:
pytest src/mcp-service -q
# Phải xanh hoàn toàn
```

#### Bước 9: Cập nhật `config.yaml` mcp-service

```yaml
# Đổi hr_query.params:
hr_query:
  enabled: ${TOOL_HR_QUERY_ENABLED:-0}
  params:
    hr_service_url: ${HR_SERVICE_URL:-http://hr-service:8004}
    internal_token: ${HR_SERVICE_INTERNAL_TOKEN:-}
# Xóa hoàn toàn dòng database_url
```

```bash
# Kiểm tra không còn MCP_DATABASE_URL trong config:
grep -r "MCP_DATABASE_URL" src/mcp-service/
# Phải không có kết quả

pytest src/mcp-service -q   # phải xanh
```

**Checkpoint Phase 2:** `pytest src/mcp-service` xanh với test đã đổi sang mock httpx. Config không còn `database_url`. Tool vẫn disabled (`TOOL_HR_QUERY_ENABLED=0`).

---

### Phase 3 — Integration test hai service

**Mục tiêu:** xác nhận luồng thật `mcp-service → hr-service → DB` hoạt động trước khi xóa code cũ.

#### Bước 10: Chạy integration test thủ công

```bash
# Terminal 1 — chạy hr-service
cd src/hr-service
DATABASE_URL=postgresql://localhost/hr_db_test \
HR_INTERNAL_TOKEN=dev-secret \
uvicorn app.main:app --port 8004

# Terminal 2 — chạy migration trước
DATABASE_URL=postgresql://localhost/hr_db_test \
alembic -c src/hr-service/alembic.ini upgrade head

# Terminal 3 — curl kiểm tra hr-service trực tiếp
curl -s -X POST http://localhost:8004/hr/query \
  -H "Content-Type: application/json" \
  -H "X-Internal-Token: dev-secret" \
  -d '{"user_id": "11111111-1111-4111-8111-111111111111", "intent": "leave_balance"}' \
  | python -m json.tool
# Expected: {"intent": "leave_balance", "data": {...}, "summary": "..."}

# Terminal 4 — chạy mcp-service với tool bật + trỏ vào hr-service
cd src/mcp-service
TOOL_HR_QUERY_ENABLED=1 \
HR_SERVICE_URL=http://localhost:8004 \
HR_SERVICE_INTERNAL_TOKEN=dev-secret \
uvicorn app.main:app --port 8003

# Terminal 5 — gọi qua mcp-service
curl -s -X POST http://localhost:8003/... \
  # (dùng MCP client hoặc script e2e hiện có)
```

**Các case phải pass:**
- `leave_balance` / `leave_requests` / `attendance` / `onboarding` trả đúng `{ intent, data, summary }`
- User A không thấy data User B (gọi với 2 user_id khác nhau, verify data khác nhau)
- `hr-service` down → mcp-service trả 5xx (verify() fail-closed khi startup)
- `X-Internal-Token` sai → hr-service trả 401 → mcp-service bubble up lỗi

**Checkpoint Phase 3:** tất cả case pass. Đây là điểm duy nhất được phép bật `TOOL_HR_QUERY_ENABLED=1`.

---

### Phase 4 — Dọn dẹp mcp-service

**Mục tiêu:** xóa code HR khỏi mcp-service. Chỉ làm sau khi Phase 3 pass.

#### Bước 11: Xóa file infrastructure HR

```bash
# Xóa theo thứ tự — từ leaf đến root
git rm src/mcp-service/app/infrastructure/db/postgres_hr_repository.py
git rm src/mcp-service/app/infrastructure/db/models.py

# Kiểm tra __init__.py còn dùng không:
cat src/mcp-service/app/infrastructure/db/__init__.py
# Nếu rỗng hoặc chỉ có __all__ = [] → xóa
git rm src/mcp-service/app/infrastructure/db/__init__.py

pytest src/mcp-service -q   # phải xanh
```

#### Bước 12: Xóa domain HR

```bash
git rm src/mcp-service/app/domain/repositories/hr_repository.py

pytest src/mcp-service -q   # phải xanh
```

#### Bước 13: Tách DTO HR khỏi tool_io.py

`tool_io.py` hiện chứa cả `RagSearchInput` (vẫn cần) và DTO HR (chuyển sang hr-service). **Không xóa file**, chỉ xóa phần HR:

```python
# Xóa khỏi mcp-service/app/domain/entities/tool_io.py:
# HrQueryInput, LeaveBalanceDTO, LeaveRequestDTO, PayrollDTO,
# AttendanceDTO, OnboardingItemDTO, OnboardingDTO, HrQueryResult

# Giữ lại:
# RagSearchInput
```

```bash
pytest src/mcp-service -q   # phải xanh — nếu đỏ, có file nào còn import DTO HR
```

Để tìm import còn sót:

```bash
grep -r "LeaveBalanceDTO\|HrQueryResult\|AttendanceDTO\|OnboardingDTO\|PayrollDTO" \
  src/mcp-service/ --include="*.py"
# Không được có kết quả nào (ngoài __pycache__)
```

#### Bước 14: Xóa migrations và alembic.ini khỏi mcp-service

```bash
git rm -r src/mcp-service/migrations/
git rm src/mcp-service/alembic.ini

# Kiểm tra requirements.txt
grep -E "sqlalchemy|psycopg2|alembic" src/mcp-service/requirements.txt
# Nếu không còn code nào dùng SQLAlchemy trong mcp-service → xóa khỏi requirements.txt
```

```bash
pytest src/mcp-service -q   # lần cuối — phải xanh hoàn toàn
```

**Checkpoint Phase 4:** `pytest src/mcp-service` xanh. `grep -r "hr_mock\|PostgresHrRepository\|HrRepository" src/mcp-service/` không có kết quả nào trong file `.py`.

---

### Rollback Plan

| Phase | Cách rollback |
|---|---|
| Phase 1 | `git checkout src/mcp-service` — hr-service chưa ảnh hưởng mcp-service |
| Phase 2 (trước khi xóa) | `git checkout src/mcp-service/app/tools/hr_query.py` — khôi phục bản DB cũ |
| Phase 2 (sau khi xóa test) | `git revert <commit>` — test cũ vẫn còn trong git history |
| Phase 3 | Tắt tool: `TOOL_HR_QUERY_ENABLED=0` — hệ thống về trạng thái disabled, không ai bị ảnh hưởng |
| Phase 4 | `git revert <commit>` từng bước — mỗi bước xóa là một commit riêng |

**Nguyên tắc rollback nhanh:** vì `TOOL_HR_QUERY_ENABLED=0` là default, rollback khẩn cấp chỉ cần đảm bảo biến đó không được set trong môi trường production. Không cần revert code ngay.

---

### Checklist tổng — trước khi merge PR

- [ ] `pytest src/mcp-service -q` xanh
- [ ] `pytest src/hr-service -q` xanh
- [ ] `grep -r "MCP_DATABASE_URL" src/mcp-service/` → không có kết quả
- [ ] `grep -r "hr_mock" src/mcp-service/ --include="*.py"` → không có kết quả
- [ ] `grep -r "PostgresHrRepository\|HrRepository" src/mcp-service/ --include="*.py"` → không có kết quả
- [ ] `grep -r "LeaveBalanceDTO\|OnboardingDTO" src/mcp-service/ --include="*.py"` → không có kết quả
- [ ] Integration test thủ công (Phase 3) pass với cả 4 intent
- [ ] `X-Internal-Token` sai → 401 (không bao giờ 200)
- [ ] User A không thấy data User B
- [ ] `TOOL_HR_QUERY_ENABLED=0` vẫn là default trong config.yaml mcp-service
- [ ] `alembic upgrade head` + `alembic downgrade base` chạy sạch trên hr-service
