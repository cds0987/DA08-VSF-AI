# mcp-service - RAG Engineer (Tran Thanh Nguyen)

MCP tool server search-only cho `rag_search`. Service nay doc Qdrant, embed query, rerank top-k, va tra ve chunk metadata de `query-service` cite nguon.

## Runtime contract

- Transport: Streamable HTTP
- Default endpoint: `http://localhost:8003/mcp`
- Config host/port: `MCP_HOST` / `MCP_PORT`
- Tool name: `rag_search(query, document_ids?, top_k=5)`
- Output shape: `list[dict]` voi cac field `chunk_id`, `document_id`, `document_name`, `caption`, `parent_text`, `heading_path`, `score`, `page_number`, `source_gcs_uri`, `markdown_gcs_uri`

## Notes

- `document_ids` duoc nhan de tuong thich chu ky MCP; search tool khong tu filter ACL.
- Reranker ho tro `none`, `lexical`, `llm`. Neu `llm` loi hoac timeout, service fallback ve vector-order (`NoopReranker`) va khong lam vo `rag_search`.
- Fallback la best-effort: co the van tra ve hit duoi threshold rerank vi `NoopReranker` giu thu tu vector score thay vi ap nguong LLM.
- Startup fail-closed: `verify_contract()` chay truoc khi serve. Neu collection/dimension/fingerprint lech voi rag-worker, process se thoat som.
- `hr_query`: da co tool server-side mock trong mcp-service cho HR ca nhan (leave_balance / leave_requests / attendance / onboarding), luon filter `user_id`. Query-service van co mock phia client de giu luong test on dinh.
