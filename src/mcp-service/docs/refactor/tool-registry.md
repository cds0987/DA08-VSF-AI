# Refactor guide (dev): tool pluggable theo OCP/SOLID + discovery cho query-service

> Trạng thái: 🟡 PROPOSED — guide cho đội dev. Cần SA chốt các điểm ⚠️ trước khi vào Phần B/D4.
> Mục tiêu một câu: **thêm một tool kiểu "summary" chỉ cần implement bên mcp-service; query-service không sửa dòng nào.**
>
> Triết lý thực thi: **strangler + incremental**. Mỗi bước phải để `pytest` của cả hai service XANH và e2e không gãy trước khi sang bước kế. KHÔNG đập đi làm lại; thêm đường mới song song đường cũ rồi mới gỡ đường cũ.

---

## 0. Bối cảnh & vấn đề (đọc để hiểu "tại sao")

`rag_search` hiện hard-code trong `build_mcp` ([app/interfaces/mcp_server.py](../../app/interfaces/mcp_server.py)) qua `@mcp.tool()`; `main.py` gọi thẳng `service.verify_contract()` / `aclose()` của riêng `SearchService`. Thêm `hr_query` → phải **sửa** `build_mcp` + `main.py` (vi phạm OCP).

Phía query-service tệ hơn — thêm một tool phải sửa **5 chỗ**:

1. typed method trong `app/infrastructure/external/mcp_client.py`
2. DTO + parser (`_hr_result_from_payload`, `_search_result_from_payload`)
3. `VALID_TOOL_NAMES` / `VALID_HR_INTENTS` trong `app/application/tool_decision.py`
4. prompt hardcode shape tool trong `app/infrastructure/external/tool_decision_client.py`
5. mock client cho test

Guide này áp pattern registry + config-driven của rag-worker (`core_engine/registry.py`, `parser.impl`+`params`+`readers`) cho mcp-service, và chuyển query-service sang **MCP-native discovery**.

---

## 1. ĐỌC TRƯỚC KHI LÀM (bắt buộc)

### 1.1 rag-worker — học pattern (chỉ đọc, không sửa)
| File | Rút ra |
|---|---|
| `src/rag-worker/core_engine/registry.py` | `Registry[T]` generic: register/get/available, guard trùng tên, entry-point lazy, built-in thắng. **Sẽ copy nguyên.** |
| `src/rag-worker/app/interfaces/api/composition.py` | Cách `register_parser` + `resolve_parser(name, params, dep)` — khuôn mẫu cho `register_tool`/`resolve_tool`. |
| `src/rag-worker/core_engine/config_loader.py`, `config_schema.py` | Cách `${ENV:-default}` resolve + pydantic schema cho `impl`/`params`. mcp-service đã có bản `_expand` riêng trong `app/core/config.py`. |
| `src/rag-worker/app/interfaces/api/runtime.py` (build_parser/build_engine_from_config) | Composition root lặp config → resolve → wire. |

### 1.2 mcp-service — sẽ sửa
| File | Phải nắm trước khi đụng |
|---|---|
| `app/interfaces/mcp_server.py` | `build_mcp` trả `(mcp, SearchService)`; `_hit_to_dict`; `InternalTokenAuthMiddleware`. |
| `app/main.py` | `_verify_and_reset(service)` (verify rồi drop client để serving loop lazy-init theo event loop của nó), `_close_service`, uvicorn run. **Pattern drop-client-sau-verify PHẢI giữ.** |
| `app/core/config.py` | `McpSettings` (frozen dataclass), `load_settings`, `_resolve`/`_expand`, `_active_profile`. Sẽ thêm `tool_spec()` + giữ raw profile. |
| `app/core/search.py` | `SearchService`, `build_search_service(settings)`, `verify_contract`, `aclose`. **Không đổi logic**, chỉ bị `RagSearchTool` bọc lại. |
| `app/core/embedding.py`, `rerank.py`, `vectorstore.py` | Chỉ đọc để biết `build_embedder`/`build_reranker`/`QdrantReader` — KHÔNG sửa. |
| `config.yaml` | Cấu trúc `active`/`profiles`/`${ENV:-default}`, các section `embedder`/`reranker`/`vector_store`. |
| `tests/test_mcp_server.py`, `tests/test_search_service.py` | Biết test đang assert gì trên `build_mcp`/`SearchService` → cập nhật cùng lúc với đổi signature. |
| `docs/maintool/hr_query.md`, `docs/maintool/rag_search.md` | Scope + boundary từng tool. |

### 1.3 query-service — sẽ sửa (Phần D)
| File | Phải nắm trước |
|---|---|
| `app/application/ports.py` | Protocol `MCPToolClient` (`list_tools`/`rag_search`/`hr_query`), `SearchResultLike`, `HrQueryResultLike`, `ToolDecisionClient`, `RouteDecisionProvider`. **Đây là contract orchestration phụ thuộc.** |
| `app/application/use_cases/query/orchestration.py` | `_handle_rag` (ACL post-filter theo `result.document_id`, threshold theo `result.score`, semantic cache) và `_handle_hr` (stream `result.summary`). **Logic RAG là bespoke, không generic hóa được — đừng cố.** |
| `app/infrastructure/external/mcp_client.py` | `MCPStreamableHttpClient` (`list_tools`, `_call_tool`, `_session`), `MockMCPClient`, các parser. |
| `app/infrastructure/external/tool_decision_client.py` | `OpenAIToolDecisionClient.choose_tool` (prompt hardcode), `MockToolDecisionClient`. |
| `app/application/tool_decision.py`, `route_decision.py`, `query_router.py` | `VALID_TOOL_NAMES`/`VALID_HR_INTENTS`, `coerce_route_decision`, `QueryRouter` (đang là `route_decision_provider`). |
| `app/interfaces/api/dependencies.py` | `get_mcp_client` (real vs mock theo `mcp_mode`), `get_query_router`, `reset_state_for_tests`, `lru_cache`. |
| `conftest.py`, `tests/test_mcp_streamable_client.py`, `tests/test_integration_behaviors.py`, `tests/test_qa.py` | Tập test phải giữ xanh. |

### 1.4 Docs nền (đọc nhanh)
- `docs/mcp-query-integration.md` (root) — hợp đồng mcp↔query hiện tại.
- `docs/contracts.md`, `docs/data-schema.md` (root, nếu có) — nơi sẽ ghi reserved-param set + HR schema.
- `infra/scripts/init-db.sql` — DB provisioning (cho Phần B).

---

## 2. BẤT BIẾN KHÔNG ĐƯỢC PHÁ (flow run invariants)

Trước mỗi PR, tự kiểm các điều sau vẫn đúng:

1. **Startup fail-closed mcp-service**: `verify_contract()` chạy TRƯỚC khi serve; lệch contract → exit code 1. (Hiện ở `_verify_and_reset`.)
2. **Drop-client-sau-verify**: client tạo lúc verify phải được đóng để serving loop lazy-init client mới bind đúng event loop của uvicorn. Mọi tool `verify()` xong phải `aclose()`.
3. **MCP wire `rag_search`**: tên tool, chữ ký `(query, document_ids?, top_k?)`, và output shape (`results[]` với `chunk_id/document_id/document_name/caption/parent_text/heading_path/score/page_number/source_gcs_uri/markdown_gcs_uri`) GIỮ NGUYÊN — query-service đang parse đúng các field này.
4. **Auth**: `X-Internal-Token` middleware bật khi có token.
5. **query-service orchestration**: `_handle_rag` vẫn nhận object có `.document_id`/`.score`/`.document_name`/... ; `_handle_hr` vẫn nhận object có `.summary`/`.intent`. ACL post-filter + score threshold + semantic cache KHÔNG đổi hành vi.
6. **Routing fallback**: tool decision lỗi → fallback `rag_search` (orchestration `_choose_route` đã bọc try/except — giữ).
7. **Mock mode**: `MCP_MODE=mock` và `LLM_MODE=mock` vẫn chạy full luồng cho test/CI.
8. **Tests xanh**: `pytest` mcp-service + query-service + e2e (`scripts/e2e_search.py`, CI rag-worker→mcp) xanh sau mỗi bước.

> Nếu một bước buộc phải đổi signature dùng chung (vd `build_mcp` return type, `MCPToolClient.list_tools`), đổi **cùng PR** với mọi caller + test, hoặc thêm method mới song song (strangler) và để caller cũ chạy tiếp.

---

## 3. Phần A — Khung tool pluggable (mcp-service)

### A1. `app/tools/registry.py` — copy Registry
- Copy nguyên nội dung `src/rag-worker/core_engine/registry.py`. Đổi docstring/nhãn cho mcp-service. Logic giữ nguyên: `register(name, factory, *, override=False)`, `get(name)`, `available()`, `_ensure_entry_points()`.
- **Compat:** file mới, không đụng gì đang chạy.
- **Verify:** `pytest tests/ -q` vẫn xanh (chưa ai dùng).

### A2. `app/tools/base.py` — port + resolver
```python
from __future__ import annotations
from typing import Any, Callable, Mapping, Protocol, runtime_checkable
from app.core.config import McpSettings
from app.tools.registry import Registry

@runtime_checkable
class McpTool(Protocol):
    name: str
    def register(self, mcp: Any) -> None: ...          # gắn @mcp.tool() (giữ typed schema)
    async def verify(self) -> None: ...                # startup fail-closed; no-op nếu không cần
    async def aclose(self) -> None: ...                # giải phóng client/pool

ToolFactory = Callable[[McpSettings, Mapping[str, Any]], McpTool]
_TOOL_REGISTRY: Registry[ToolFactory] = Registry("tool", entry_point_group="mcp_service.tool")

def register_tool(name: str, factory: ToolFactory, *, override: bool = False) -> None:
    _TOOL_REGISTRY.register(name, factory, override=override)

def resolve_tool(name: str, *, settings: McpSettings, params: Mapping[str, Any]) -> McpTool:
    return _TOOL_REGISTRY.get(name)(settings, dict(params or {}))

def available_tools() -> list[str]:
    return _TOOL_REGISTRY.available()
```
- **SOLID:** SRP (1 tool/file) · OCP (thêm tool không sửa server) · LSP (thay qua port) · ISP (`verify`/`aclose` no-op được) · DIP (server phụ thuộc abstraction). Bên thứ ba: `[project.entry-points."mcp_service.tool"]`.
- **DoD:** unit test `tests/test_tool_registry.py`: đăng ký fake tool, resolve đúng instance, trùng tên raise, `available_tools()` chứa tên.

### A3. config.yaml + `McpSettings.tool_spec`
config.yaml — bỏ ý tưởng wrapper `tools:`; mỗi tool là **key top-level**. Phân cấp dứt khoát: chỉ `common`/`server` ở cấp service; **mọi config thuộc tool nào thì nest hẳn vào tool đó** (không để lộn xộn ở top-level). rag_search sở hữu toàn bộ config search của nó (embedder/vector_store/vectorstore_contract/reranker/retrieval); hr_query sở hữu `params.database_url`. Registry quyết định tool nào tồn tại; không có section → `enabled` mặc định true.
```yaml
    common:   { ai_mode: ..., timeout: ..., max_retries: ... }   # cấp service
    server:   { host: ..., port: ..., internal_token: ... }      # cấp service

    rag_search:
      enabled: ${TOOL_RAG_SEARCH_ENABLED:-1}
      embedder:        { model: ..., base_url: ..., api_key: ..., dimension: ... }
      vector_store:    { impl: qdrant, params: { collection, url, api_key, ... } }
      vectorstore_contract: { provider: ..., collection: ..., embed_model: ... }
      reranker:        { impl: ..., model: ..., timeout_seconds: ..., params: {...} }
      retrieval:       { top_k_candidates: ..., rerank_top_k: ..., rerank_threshold: ... }

    hr_query:
      enabled: ${TOOL_HR_QUERY_ENABLED:-0}
      params:
        database_url: ${MCP_DATABASE_URL:-}
```
> **Lưu ý loader:** `load_settings` đọc embedder/vector_store/reranker/retrieval từ subtree `rag_search` trước, **fallback** về top-level nếu không có (tương thích ngược config cũ). `McpSettings` giữ field phẳng như cũ nên `SearchService`/`contract()`/`main.py` KHÔNG đổi — chỉ NGUỒN đọc dời vào trong tool.
`app/core/config.py`:
- Thêm dataclass `ToolSpec(enabled: bool, params: Mapping[str, Any])`.
- `McpSettings` lưu thêm `tools_profile: Mapping[str, Any]` (phần profile đã resolve, để tra theo tên). **Giữ mọi field cũ** để không vỡ caller.
- Method:
```python
def tool_spec(self, name: str) -> ToolSpec:
    node = self.tools_profile.get(name) or {}
    enabled_raw = str(node.get("enabled", "1")).strip().lower()
    return ToolSpec(enabled=enabled_raw in {"1","true","yes","on"},
                    params=node.get("params") or {})
```
- `load_settings`: gán `tools_profile=profile` (dict đã `_resolve`). Không suy đoán key nào là tool — chỉ tra đúng tên registry hỏi.
- **Compat:** thêm field có default → `McpSettings(...)` cũ vẫn dựng được; test config cập nhật nếu so khớp toàn bộ field.
- **DoD:** `tests/test_config.py` thêm case `tool_spec("hr_query").enabled == False` mặc định, `tool_spec("rag_search").enabled == True`.

### A4. `RagSearchTool` trước, rồi mới đổi `build_mcp`
**Thứ tự quan trọng để không vỡ:** tạo tool mới TRƯỚC, chạy test riêng, rồi mới chuyển `build_mcp` sang dùng nó.

`app/tools/rag_search.py`:
```python
from app.core.search import build_search_service
from app.core.vectorstore import SearchHit
from app.tools.base import register_tool

def _hit_to_dict(hit: SearchHit) -> dict: ...   # bê từ mcp_server.py

class RagSearchTool:
    name = "rag_search"
    def __init__(self, settings, params):
        self._service = build_search_service(settings)
    def register(self, mcp):
        service = self._service
        @mcp.tool()
        async def rag_search(query: str, document_ids: list[str] | None = None,
                             top_k: int | None = None) -> dict:
            """Search internal company documents; scope by document_ids when provided."""
            hits = await service.rag_search(query, document_ids=document_ids, top_k=top_k)
            return {"results": [_hit_to_dict(h) for h in hits]}
    async def verify(self): await self._service.verify_contract()
    async def aclose(self): await self._service.aclose()

register_tool("rag_search", lambda s, p: RagSearchTool(s, p))
```
- Output shape `results[]` **byte-for-byte như cũ** (invariant #3).
- **DoD:** test gọi `RagSearchTool(settings, {}).register(fake_mcp)` đăng ký được 1 tool tên `rag_search` với schema mong đợi.

### A5. `app/tools/__init__.py` — import built-in
```python
from app.tools import rag_search   # noqa: F401  (chạy register_tool)
# from app.tools import hr_query   # bật ở Phần B
```
Hoặc dùng dynamic `import_module(f"app.tools.{spec.impl}")` lúc resolve. **Đề xuất import tường minh built-in** cho rõ.

### A6. `build_mcp` lái bằng registry — `app/interfaces/mcp_server.py`
```python
import app.tools  # noqa: F401 — kích hoạt register_tool built-in
from app.tools.base import available_tools, resolve_tool

def build_mcp(settings: McpSettings | None = None) -> tuple[Any, list]:
    from mcp.server.fastmcp import FastMCP
    settings = settings or load_settings()
    mcp = FastMCP("mcp-service", host=settings.host, port=settings.port,
                  stateless_http=True, json_response=True)
    tools = []
    for name in available_tools():
        spec = settings.tool_spec(name)
        if not spec.enabled:
            continue
        tool = resolve_tool(name, settings=settings, params=spec.params)
        tool.register(mcp)
        tools.append(tool)
    if not tools:
        # fail-closed: prod raise; dev log cảnh báo (đề xuất raise ở mọi env vì server vô dụng)
        raise RuntimeError("no MCP tool enabled")
    return mcp, tools
```
- **BREAKING (in-repo):** return `(mcp, list[McpTool])` thay `(mcp, SearchService)`. Sửa `main.py` + `tests/test_mcp_server.py` **cùng PR**.
- Giữ `InternalTokenAuthMiddleware`, `build_mcp_middleware`.

### A7. `main.py` generic hóa — `app/main.py`
```python
mcp, tools = build_mcp(settings)

async def _verify_and_reset(tools) -> None:
    try:
        for t in tools:
            await t.verify()              # giữ fail-closed (invariant #1)
    finally:
        for t in tools:
            await t.aclose()              # giữ drop-client (invariant #2)
...
finally:
    asyncio.run(_close_all(tools))        # for t: await t.aclose()
```
- `VectorstoreContractError` từ `RagSearchTool.verify` vẫn bong lên → exit 1. Giữ thứ tự log `mcp_contract_verified`.
- **DoD Phần A:** `pytest` mcp-service xanh; `scripts/e2e_search.py` xanh; khởi động thật thấy log verify + serve như trước.

---

## 4. Phần D — Discovery cho query-service (MCP-native)

### Nguyên tắc + ranh giới thực tế (đọc kỹ)
- **Tầng routing (chọn tool + args): generic hóa hoàn toàn** — đây là phần thắng lớn.
- **Tầng tiêu thụ kết quả: có 2 loại tool:**
  - **"summary-style"** (vd hr_query, đa số tool tương lai): trả `{summary, data}` → query-service stream `summary` qua LLM bằng **một handler generic** → thêm tool loại này = **0 sửa query-service**.
  - **"bespoke"** (rag_search): cần ACL post-filter + score threshold + semantic cache → giữ handler riêng đã có. Đây là ngoại lệ hợp lý, KHÔNG cố generic hóa.
- ⇒ Định nghĩa **contract kết quả tool**: mọi tool trả tối thiểu `{"summary": str}` (kèm `data`/`results` tùy ý). Tool bespoke khai báo cờ riêng để orchestration route vào handler đặc thù (xem D4b).

### D1. Discovery: thêm `list_tool_specs()` (strangler — KHÔNG đổi `list_tools`)
- Trong `mcp_client.py`, thêm dataclass + method MỚI, giữ `list_tools() -> list[str]` cũ (suy ra tên từ specs) để routing cũ không gãy:
```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict

class MCPStreamableHttpClient:
    async def list_tool_specs(self) -> list[ToolSpec]:
        async with self._session() as s:
            resp = await s.list_tools()
        return [ToolSpec(t.name, getattr(t, "description", "") or "",
                         getattr(t, "inputSchema", {}) or {}) for t in resp.tools]
    async def list_tools(self) -> list[str]:               # giữ nguyên cho code cũ
        return [t.name for t in await self.list_tool_specs()]
```
- Cache TTL ngắn (vd 60s) hoặc nạp lúc startup; tool ít đổi.
- **Compat:** `MockMCPClient.list_tool_specs()` trả spec tĩnh tương ứng `rag_search`/`hr_query` (lấy mô tả + schema tay). `list_tools()` cũ giữ nguyên.

### D2. Routing native tool-use (thay prompt hardcode)
- `OpenAIToolDecisionClient.choose_tool`: nhận thêm khả năng đọc `list_tool_specs()`; truyền `tools=[{name, description, parameters: model_visible_schema}]` vào function-calling thay vì nhồi shape vào instruction string.
- **Xóa** phụ thuộc `VALID_TOOL_NAMES`/`VALID_HR_INTENTS`. Validity = `name ∈ specs` + validate `arguments` theo `input_schema` (dùng `jsonschema`).
- Sai/timeout → trả `ToolDecision(rag_search)` (giữ fallback hiện có).
- **Compat strangler:** thêm cờ `settings.tool_routing_mode = "native" | "legacy"`. Mặc định `legacy` để CI/mock cũ chạy y nguyên; bật `native` khi sẵn sàng. Khi `native` ổn định mới xóa nhánh legacy + `VALID_*`.

### D3. Gọi tool generic
- Public hóa `call_tool(name, arguments) -> dict` (đã có `_call_tool`). Giữ `rag_search()`/`hr_query()` như **adapter mỏng** gọi `call_tool` để orchestration cũ không gãy.
- `MCPToolClient` (ports.py): thêm `list_tool_specs` + `call_tool` vào Protocol; giữ method cũ → orchestration không phải đổi ngay.

### D4. ⭐ Guardrail: server tiêm identity/ACL (quan trọng nhất)
Model KHÔNG bao giờ được điền identity/ACL. Cơ chế **generic keyed theo tên property** (không rẽ nhánh theo tool):
- Reserved set: `user_id` ← JWT (`user.id`); `document_ids` ← ACL (`document_access_repo`); `top_k` ← default server.
- (a) **Schema model thấy** = `input_schema` đã *lược bỏ* property reserved → model không bị hỏi tới.
- (b) **Trước khi `call_tool`**: orchestration *tiêm/ghi đè* các param này từ context, *strip* giá trị model tự điền.
- ⇒ Tool mới khai báo `user_id` → tự được tiêm JWT, 0 sửa query-service.

### D4b. Định tuyến result generic vs bespoke
- Orchestration: nếu tool == `rag_search` → `_handle_rag` (giữ nguyên). Ngược lại → `_handle_generic_tool`:
```python
async def _handle_generic_tool(self, *, tool_name, arguments, user, ...):
    args = self._inject_reserved(tool_name, arguments, user)   # D4
    payload = await self._mcp_client.call_tool(tool_name, args)
    context_text = str(payload.get("summary") or "")
    # stream qua LLM y như _handle_hr hiện tại
```
- `_handle_hr` hiện tại trở thành trường hợp riêng của generic (summary-based) → có thể gộp, hoặc giữ tới khi `native` ổn.
- **Compat:** khi `tool_routing_mode=legacy`, đường cũ (`_handle_hr` + typed `hr_query`) chạy nguyên. `native` mới đi vào `_handle_generic_tool`.

### D5. Mock + tests
- `MockMCPClient`: thêm `list_tool_specs()` (spec tĩnh) + `call_tool(name, args)` generic (đọc `MOCK_HR_DATA`/`MOCK_DOCUMENTS`). Giữ `rag_search()`/`hr_query()` cũ tới khi cắt legacy.
- Tests mới: validate arguments theo schema; user A không thấy data user B (tiêm `user_id` từ JWT, model điền `user_id` khác bị strip); tool lạ → fallback rag_search.
- **DoD Phần D:** bật `tool_routing_mode=native` trong một CI job; `test_integration_behaviors.py`/`test_qa.py` xanh ở cả `legacy` lẫn `native`.

---

## 5. Phần B — hr_query đầy đủ (mcp-service)

> Theo `docs/maintool/hr_query.md`. DB riêng mcp-service. Đọc-only, **luôn `WHERE user_id = :current_user`**.

### B1. Hạ tầng DB (`mcp_db`)
- mcp-service chưa có DB layer. Theo rag-worker: SQLAlchemy sync + `asyncio.to_thread`, Alembic. Thêm `requirements.txt`: sqlalchemy, alembic, psycopg.
- Đồng bộ `infra/scripts/init-db.sql`.
- ⚠️ **SA:** chung Postgres instance (schema riêng) hay DB tách? doc nói database-per-service → đề xuất `mcp_db` riêng.

### B2. Schema HR — toàn bộ intent
- Bảng: `leave_balance`, `leave_requests`, `payroll`, `benefits`, `attendance`, `onboarding`, `performance`, `recruitment`. Mọi bảng có `user_id` + index theo `user_id`.
- ⚠️ `employee_profile`/`org_structure`: **chốt nguồn (user-service vs HRIS) TRƯỚC** — tránh trùng sở hữu data. Tách sub-task, chưa tạo bảng.
- Migration `0001_create_hr_schema` + seed khớp `user_id` user-service.

### B3. Contract `HrQueryResult`
- Envelope `{intent, data: <typed theo intent>, summary}`. `summary` cho LLM dùng thẳng (đúng contract D4b summary-style). Đồng bộ `docs/contracts.md` + khớp DTO query-service (`tool_decision.py`/`mcp_client.py`).

### B4. Repository (luôn filter user_id)
- Port `HrRepository` + adapter Postgres. Mọi method nhận `user_id` và **bắt buộc** filter; không có tham số định danh khác.
- Map `intent → handler` nội bộ tool. Thêm intent = thêm handler (OCP cả tầng tool lẫn intent).

### B5. `app/tools/hr_query.py` — `HrQueryTool`
```python
from typing import Literal
class HrQueryTool:
    name = "hr_query"
    def __init__(self, settings, params):
        self._repo = build_hr_repository(params.get("database_url") or "")
    def register(self, mcp):
        repo = self._repo
        @mcp.tool()
        async def hr_query(user_id: str,
                           intent: Literal["leave_balance","leave_requests","payroll"]) -> dict:
            """Read the CURRENT user's own HR record. user_id is injected by the
            caller from JWT and must never be guessed by the model."""
            return await query_hr(repo, user_id=user_id, intent=intent)  # luôn WHERE user_id
    async def verify(self): await self._repo.ping()      # fail-closed nếu chưa migrate
    async def aclose(self): await self._repo.aclose()
register_tool("hr_query", lambda s, p: HrQueryTool(s, p))
```
- `Literal[...]` → FastMCP sinh enum trong inputSchema → query-service/model thấy intent hợp lệ tự động (Phần D).
- intent invalid → lỗi rõ ràng, không lộ data.
- Bật trong `app/tools/__init__.py` + `config.yaml` (`TOOL_HR_QUERY_ENABLED=1`).

### B6. Quyền nhạy cảm
- ⚠️ `payroll`/`benefits`/`performance`/`recruitment`: role-based (vd `recruitment` chỉ hiring manager) + audit/trace; không lộ qua `summary`. **Nguồn role?** (JWT claim query-service truyền). Giai đoạn đầu bật intent độ nhạy Thấp/Trung bình.

### B7. Nối query-service
- Khi Phần D `native` bật: hr_query chạy qua `_handle_generic_tool`, **không cần** map tay. Khi còn `legacy`: cập nhật `MockMCPClient.hr_query`/parser cho khớp contract thật.

### B8. Tests
- user A không xem data user B; intent invalid → error rõ; contract `HrQueryResult` ổn định; e2e query→mcp `hr_query`.

---

## 6. Thứ tự PR + checkpoint + rollback

| PR | Nội dung | Checkpoint (phải xanh) | Rollback |
|---|---|---|---|
| 1 | A1–A3 (registry, base, config) | unit test registry/config; chưa ai dùng | xóa thư mục `app/tools/` |
| 2 | A4–A7 (RagSearchTool + build_mcp + main) | pytest mcp + e2e_search; startup verify như cũ | revert build_mcp/main về bản hard-code |
| 3 | D1 (list_tool_specs) + D3 (call_tool) song song | pytest query (đường cũ nguyên) | gỡ method mới |
| 4 | D2+D4+D4b sau cờ `tool_routing_mode=native` (mặc định legacy) | CI 2 job: legacy + native đều xanh | tắt cờ → legacy |
| 5 | B1–B5 (hr_query thật) sau SA chốt ⚠️ | migrate + seed + tool test | `TOOL_HR_QUERY_ENABLED=0` |
| 6 | Cắt legacy: xóa `VALID_*`, prompt hardcode, typed method thừa | toàn bộ test xanh ở native | giữ PR4 cờ làm phao |

**Quy tắc vàng:** không bao giờ gộp "đổi signature dùng chung" với "thêm tính năng" trong một PR mà chưa cập nhật hết caller + test.

---

## 7. ⚠️ Điểm SA phải chốt trước khi code phần liên quan
1. **Reserved-param set** (`user_id`/`document_ids`/`top_k`) — contract ngầm mcp↔query; ghi vào `docs/contracts.md` để mọi tool mới đặt đúng tên param thì được tiêm tự động (chặn Phần D4).
2. **DB instance cho mcp_db** — chung Postgres (schema riêng) hay tách (chặn B1).
3. **Nguồn `employee_profile`/`org_structure`** — user-service vs HRIS (chặn B2).
4. **Nguồn role** cho intent nhạy cảm — JWT claim nào (chặn B6).

---

## 8. Tổng kết: vòng đời "thêm một tool"
| Bước | Trước | Sau guide |
|---|---|---|
| mcp-service | thêm `@mcp.tool` trong `build_mcp` | thêm file tool + `register_tool` (Phần A) |
| query-service (summary-style) | sửa 5 chỗ | **0 chỗ** — discovery + generic handler (Phần D) |
| query-service (bespoke như rag_search) | — | chỉ khi cần orchestration riêng (hiếm) |
| config | — | (tùy chọn) bật/tắt qua key top-level (A3) |
