# Gap 1 — Tool config chưa module hóa trong code (OCP chưa trọn)

> Phạm vi: sau commit `dd8c171` (refactor tool registry) + restructure config nest theo tool.
> Trạng thái: 🟢 ĐÃ XỬ LÝ phần lớn ở commit `d6c6b62` — xem cập nhật từng mục bên dưới. Còn lại 1.3 (nhỏ) OPEN.

## Bối cảnh

`config.yaml` đã được phân cấp sạch: chỉ `common`/`server` ở cấp service, mọi config thuộc tool nào nest hẳn vào tool đó (`rag_search.embedder/vector_store/reranker/retrieval`, `hr_query.params.database_url`). Khung `app/tools` (registry + port `McpTool`) cho phép thêm tool không sửa `build_mcp`/`main.py`.

Tuy nhiên CODE chưa tiêu thụ config theo đúng cấu trúc đó → còn 2 chỗ rò rỉ phá vỡ tinh thần OCP/module hóa.

## ✅ Đã đúng (không phải gap)

- `build_mcp` ([app/interfaces/mcp_server.py](../../app/interfaces/mcp_server.py)): lặp `available_tools()` → `resolve_tool` → `tool.register(mcp)`, không biết tên tool cụ thể. Thêm tool = thêm file + `register_tool`. ✔ OCP.
- `main.py` `_verify_and_reset` / `_close_tools`: lặp `for tool in tools` qua port `McpTool`, dùng `getattr` mềm. ✔ DIP/LSP.
- `config.yaml`: nested per-tool. ✔ (ở mức file).

---

## ✔️ Cập nhật commit `d6c6b62`

- **Gap 1.1 — ĐÃ XỬ LÝ:** `RagSearchTool` giờ dựng `RagSearchConfig.from_params(settings, params)` đọc từ subtree tool (`params.embedder/vector_store/vectorstore_contract/reranker/retrieval`), `settings` chỉ làm fallback. `tool_spec()` trả toàn bộ subtree (mọi key trừ `enabled`) làm `params`. Mọi tool giờ tiêu thụ config **qua `params`** → một quy ước thống nhất.
  - *Dư nợ kỹ thuật (chấp nhận được):* `McpSettings` vẫn giữ các field phẳng của rag_search và `RagSearchConfig.to_settings()` dùng `replace(settings, ...)` vì `build_search_service` còn nhận `McpSettings`. Tức god-object chưa co hẳn — đang đóng vai *carrier/fallback*. Co triệt để cần đổi `SearchService` nhận thẳng `RagSearchConfig` → để dành, KHÔNG chặn OCP (thêm tool mới không còn buộc sửa `McpSettings`).
- **Gap 1.2 — ĐÃ XỬ LÝ:** `main.py` bỏ `settings.contract()`/log index ở entrypoint; chuyển vào `RagSearchTool.verify()` (`mcp_tool_verify_start/ok`). Entrypoint chỉ log generic theo tool.
- **Gap 1.3 — CÒN OPEN** (xem dưới).

---

## Gap 1.1 — `RagSearchTool` vứt `params`, moi config từ `McpSettings` god-object (chính) — ✅ resolved

[app/tools/rag_search.py](../../app/tools/rag_search.py):
```python
def __init__(self, settings, params):
    del params                                       # ⚠️ vứt params
    self._service = build_search_service(settings)   # đọc field phẳng toàn cục
```

- `config.yaml` đã nest `rag_search.embedder/reranker/retrieval`, nhưng code vẫn đọc qua `McpSettings.rerank_impl`, `.top_k_candidates`, `.provider`... — field **phẳng, dùng chung** trong một dataclass lớn ([app/core/config.py](../../app/core/config.py) `McpSettings`).
- Factory ký `(settings, params)` hứa per-tool params, nhưng `rag_search` phá lời hứa: nó đọc global settings, còn `hr_query` thì lấy `database_url` qua `params` → **hai tool hai kiểu, không nhất quán**.

**Hệ quả OCP:** một tool mới cần config có cấu trúc buộc phải **sửa `McpSettings`** (thêm field) → *modify*, không *extend*. Lời hứa "thêm tool không đụng code chung" chưa trọn.

**Hướng sửa:**
- Tách `RagSearchConfig` (dataclass riêng) parse từ `params` (subtree `rag_search`); `RagSearchTool` tự dựng `SearchService` từ đó.
- `McpSettings` co lại còn cấp-service (host/port/log_level/app_env/internal_token/ai_mode). Config tool sống trong `tool_spec(name).params`.
- Mọi tool tiêu thụ config **chỉ qua `params`** → một quy ước duy nhất.

---

## Gap 1.2 — `main.py` leak kiến thức vectorstore-contract của rag_search lên cấp service — ✅ resolved

[app/main.py](../../app/main.py):
```python
contract = settings.contract()                       # ⚠️ giả định luôn có vectorstore
logger.info("mcp_startup index=%s ...", contract.index_id, ...)
...
logger.info("mcp_contract_verified index=%s", contract.index_id)
```

- `contract()` dựng từ provider/collection/embed_model/dimension — **tài sản của rag_search**, không phải của service.
- Nếu chỉ bật `hr_query` (tắt rag_search), service vẫn log một "vectorstore index" vô nghĩa.
- Verify contract đã nằm đúng chỗ trong `RagSearchTool.verify()`; phần log ở `main.py` là kiến thức tool rò rỉ vào entrypoint.

**Hướng sửa:**
- Bỏ `settings.contract()` khỏi `main.py`.
- Mỗi tool tự log chi tiết của nó trong `verify()`.
- Entrypoint chỉ log generic: số tool + tên tool đã bật.

---

## Gap 1.3 — Phụ (nhỏ) — ✅ resolved

- **Policy enabled:** `build_mcp` ([app/interfaces/mcp_server.py](../../app/interfaces/mcp_server.py)) giờ tách: nếu config khai `enabled` tường minh thì theo đó; nếu không, **built-in mặc định BẬT, tool từ entry-point bên thứ ba mặc định TẮT** (phải khai tường minh mới chạy). `Registry.is_entry_point()` + `base.is_entry_point_tool()` phân biệt nguồn; `ToolSpec.enabled_explicit` báo key có được khai không. Khóa bằng `test_entry_point_tool_disabled_without_explicit_enable`.
- **Docstring:** `mcp_server.py` đã đổi sang mô tả generic (registry-driven).

---

## Gap 1.4 — Auto-sync tool theo config.yaml (native routing) chưa bật mặc định

**Cơ chế đã có, đúng tinh thần MCP:** tool nào `enabled` trong config.yaml → `build_mcp` register → FastMCP expose qua `list_tools()`. query-service `MCPStreamableHttpClient.list_tool_specs()` discover động, `OpenAIToolDecisionClient` (khi `tool_routing_mode=native`) trình thẳng cho model làm allow-list (kèm strip reserved-param `user_id`/`document_ids`/`top_k` — guardrail D4). ⇒ Thêm/tắt tool ở mcp-service tự phản ánh sang model, **không sửa query-service** (chỉ cần restart mcp-service).

**Trạng thái:**
- ✅ Native path implement đầy đủ + test (`test_query_hardening`).
- ✅ TTL cache cho `list_tool_specs` đã thêm (`Settings.mcp_tool_cache_ttl_seconds`), **mặc định 0 (off)** để an toàn; production bật qua `MCP_TOOL_CACHE_TTL_SECONDS`.
- 🔴 **`tool_routing_mode` vẫn mặc định `legacy`.** Thử bật `native` mặc định làm **vỡ 22 test** → revert. Hai blocker thật:
  1. **Bug native rớt `outcome`:** nhánh `_fallback` ([orchestration.py](../../../query-service/app/application/use_cases/query/orchestration.py) ~dòng 434/443) yield done-event thiếu key `outcome`; native routing đẩy một số route (off_topic/identity) vào fallback → `KeyError: 'outcome'`. Cần thêm `outcome` vào done-event fallback (hoặc không route các case đó vào fallback).
  2. **Test legacy pin hành vi cũ:** ~21 test mã hóa kỳ vọng routing legacy → cần migrate sang native.

**Việc cần để bật native mặc định (commit riêng):** vá #1 (done-event fallback), migrate #2, rồi đổi default `tool_routing_mode=native` + để production set `MCP_TOOL_CACHE_TTL_SECONDS=60`.

---

## Việc còn lại

Không còn gap chặn OCP. Chỉ còn **tuỳ chọn dư nợ 1.1** (vệ sinh, không gấp): co `McpSettings` về cấp-service bằng cách cho `SearchService`/`build_search_service` nhận thẳng `RagSearchConfig` thay vì `McpSettings`. Lan tới `build_embedder`/`build_reranker`/`QdrantReader` + test → nên làm như một commit strangler riêng, KHÔNG gộp.

DoD: `pytest src/mcp-service/tests -q` xanh; startup vẫn fail-closed khi contract lệch (qua `RagSearchTool.verify`). ✔ hiện 35 passed.
