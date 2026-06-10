# mcp-service - RAG Engineer (Tran Thanh Nguyen)

MCP tool server search-only cho `rag_search`. Service nay doc Qdrant, embed query, rerank top-k, va tra ve chunk metadata de `query-service` cite nguon.

## Runtime contract

- Transport: Streamable HTTP
- Default endpoint: `http://localhost:8003/mcp`
- Config host/port: `MCP_HOST` / `MCP_PORT`
- Tool name: `rag_search(query, document_ids?, top_k=5)`
- Output shape: `{"results": list[dict]}` — moi dict co cac field `chunk_id`, `document_id`, `document_name`, `caption`, `parent_text`, `heading_path`, `score`, `page_number`, `source_gcs_uri`, `markdown_gcs_uri`

## Notes

- `document_ids` duoc nhan de tuong thich chu ky MCP; search tool khong tu filter ACL.
- Reranker ho tro `none`, `lexical`, `llm`. Neu `llm` loi hoac timeout, service fallback ve vector-order (`NoopReranker`) va khong lam vo `rag_search`.
- Fallback la best-effort: co the van tra ve hit duoi threshold rerank vi `NoopReranker` giu thu tu vector score thay vi ap nguong LLM.
- Startup fail-closed: `verify_contract()` chay truoc khi serve. Neu collection/dimension/fingerprint lech voi rag-worker, process se thoat som.
- `hr_query`: la HTTP proxy sang hr-service (`POST /hr/query`, header `X-Internal-Token`), tra thang `{intent, data, summary}`. mcp-service KHONG so huu HR data; hr-service filter `WHERE user_id`. Tool mac dinh TAT (`TOOL_HR_QUERY_ENABLED=0`); cau hinh qua `HR_SERVICE_URL` / `HR_SERVICE_INTERNAL_TOKEN`. 7 intent: leave_balance / leave_requests / attendance / onboarding / payroll / benefits / performance (3 cai sau la self-access + audit). Tap intent o `HrIntent`/`MVP_INTENTS` (app/tools/hr_query.py) PHAI khop `Literal` o hr-service routes.py.
