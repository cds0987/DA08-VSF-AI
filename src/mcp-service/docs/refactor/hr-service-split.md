# Tách `hr_query` thành `hr-service` độc lập

> **Trạng thái:** 🔵 Kế hoạch — chưa bắt tay implement.
> Đọc [`docs/maintool/hr_query.md`](../maintool/hr_query.md) để hiểu scope + boundary của tool trước.

---

## Bối cảnh

MVP `hr_query` hiện triển khai theo kiểu **embedded**: tool nằm trong mcp-service, kết nối thẳng vào Postgres `mcp_db.hr_mock` qua `PostgresHrRepository`. Cách này đủ để ship nhanh nhưng tạo ra hai vấn đề dài hạn:

1. **Coupling**: mcp-service phải giữ SQLAlchemy engine, Alembic migration, connection pool cho dữ liệu HR — không liên quan đến nhiệm vụ chính là route MCP tool.
2. **Scale độc lập**: nếu HR phát triển (thêm intent payroll, performance, tích hợp HRIS thật), nó cần release cycle, secret, DB config riêng — không nên kéo mcp-service theo.

Giải pháp: tách thành `hr-service` — một FastAPI service nhỏ, sở hữu toàn bộ hạ tầng HR; `hr_query` tool trong mcp-service trở thành **HTTP proxy thuần**.

---

## Kiến trúc mục tiêu

```
query-service
    │  MCP call: hr_query(user_id, intent)
    ▼
mcp-service  [hr_query tool — HTTP proxy ~40 dòng]
    │  POST /hr/query  { user_id, intent }
    │  Header: X-Internal-Token: ***
    ▼
hr-service   [FastAPI — owns Postgres]
    │  SELECT … WHERE user_id = ?
    ▼
mcp_db  (PostgreSQL, schema hr_mock)
```

**Bất biến không đổi:**
- `user_id` vẫn do MCP client (query-service) inject từ JWT — tool không tin LLM điền.
- Output contract `{ intent, data, summary }` giữ nguyên — query-service không cần sửa.
- Auth giữa mcp-service ↔ hr-service dùng `X-Internal-Token` (cùng pattern mcp-service đang dùng với query-service).

---

## hr-service: interface cấp 1

### `POST /hr/query`

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

Không thêm endpoint nào khác ở giai đoạn 1 — mỗi intent là một nhánh logic bên trong handler, không tách thành route riêng.

### `GET /health`

```
Response 200: { "status": "ok" }
```

Dùng bởi `HrQueryTool.verify()` trong mcp-service lúc startup (fail-closed).

---

## Cấu trúc hr-service

```
src/hr-service/
├── app/
│   ├── api/
│   │   ├── auth.py            # verify X-Internal-Token (constant-time compare)
│   │   └── routes.py          # POST /hr/query, GET /health
│   ├── core/
│   │   └── config.py          # HrSettings: database_url, host, port, internal_token
│   ├── domain/
│   │   ├── entities/dtos.py         # move từ mcp-service: LeaveBalanceDTO, AttendanceDTO, ...
│   │   └── repositories/hr_repository.py  # move nguyên từ mcp-service
│   └── infrastructure/db/
│       ├── models.py                 # move nguyên từ mcp-service
│       └── postgres_hr_repository.py # move nguyên từ mcp-service
├── migrations/                # move từ src/mcp-service/migrations/
├── alembic.ini                # move từ src/mcp-service/alembic.ini
├── config.yaml                # HrSettings: host, port, database_url, internal_token
├── Dockerfile
└── requirements.txt           # fastapi, uvicorn, sqlalchemy, psycopg2-binary, alembic
```

`summary` builder (các hàm `_leave_balance_summary`, `_attendance_summary`, ...) di chuyển vào `app/api/routes.py` của hr-service — mcp-service không cần tự build text.

---

## Thay đổi trong mcp-service

### `app/tools/hr_query.py` — trở thành HTTP proxy

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

### `config.yaml` — đổi params

```yaml
hr_query:
  enabled: ${TOOL_HR_QUERY_ENABLED:-0}
  params:
    hr_service_url: ${HR_SERVICE_URL:-http://hr-service:8004}
    internal_token: ${HR_SERVICE_INTERNAL_TOKEN:-}
```

`MCP_DATABASE_URL` bị xóa khỏi mcp-service config hoàn toàn.

### Files bị xóa khỏi mcp-service

| File/Folder | Action |
|---|---|
| `app/domain/repositories/hr_repository.py` | xóa |
| `app/domain/entities/tool_io.py` — các class HR | xóa phần HR; giữ `RagSearchInput` |
| `app/infrastructure/db/models.py` | xóa cả file |
| `app/infrastructure/db/postgres_hr_repository.py` | xóa cả file |
| `app/infrastructure/db/__init__.py` | xóa nếu thư mục rỗng |
| `migrations/` | move sang `src/hr-service/migrations/` |
| `alembic.ini` | move sang `src/hr-service/alembic.ini` |
| `requirements.txt` — `sqlalchemy`, `psycopg2-binary`, `alembic` | xóa nếu không còn dùng ở nơi khác |

---

## Thứ tự implement

```
[1] Tạo scaffold src/hr-service/ + Dockerfile + config.yaml
[2] Move domain/ + infrastructure/db/ + migrations/ từ mcp-service sang
[3] Viết app/api/routes.py (POST /hr/query, GET /health) + auth.py
[4] Viết app/core/config.py (HrSettings) + main.py
[5] Test hr-service độc lập: pytest + curl thủ công
[6] Sửa mcp-service/app/tools/hr_query.py thành HTTP proxy (code ở trên)
[7] Cập nhật mcp-service/config.yaml: đổi params, xóa MCP_DATABASE_URL
[8] Xóa các file domain/infrastructure không còn dùng trong mcp-service
[9] Cập nhật mcp-service tests: mock httpx thay vì mock repository
[10] Chạy tích hợp: mcp-service + hr-service cùng lúc, kiểm verify() startup
```

---

## SA Blockers còn mở

| # | Câu hỏi | Chặn bước |
|---|---|---|
| SA-3 | Nguồn role cho intent nhạy cảm (`payroll`, `performance`) — JWT claim nào để gate | Bước [3] khi mở rộng Giai đoạn 2 |
| SA-4 | Reserved-param contract `user_id` / `document_ids` trong `_inject_reserved` | Bước [9] phía query-service |

SA-1 và SA-2 đã resolved — xem [`docs/maintool/hr_query.md`](../maintool/hr_query.md#sa-blockers--phải-chốt-trước-khi-code-phần-liên-quan).

---

## Không làm trong refactor này

- Không đổi output contract — query-service không cần sửa gì.
- Không thêm intent mới — scope của refactor chỉ là tách hạ tầng.
- Không thay DB mock bằng HRIS thật — đó là Giai đoạn 2 riêng.
