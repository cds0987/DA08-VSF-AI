# Tool `rag_search`

> Trạng thái: ✅ Đã implement và chạy (search-only, expose qua MCP Streamable HTTP).

## Mục đích (Intend)

Cho phép agent (query-service hoặc agent tương lai) **tìm thông tin trong tài liệu nội bộ công ty** để trả lời câu hỏi người dùng kèm trích dẫn nguồn.

`rag_search` nhận câu hỏi (đã được rewrite ở phía gọi nếu cần), tìm trong vector store (Qdrant) các đoạn (chunk) liên quan, rerank lại, rồi trả về metadata của chunk để query-service dựng câu trả lời + cite nguồn (tên tài liệu, trang, link GCS).

## Boundary

**Tool LÀM:**
- Embed câu query, search Qdrant, rerank top-k, trả về `list[chunk]` với metadata.
- Nhận `document_ids` để tương thích chữ ký MCP (scope theo tài liệu khi được truyền).

**Tool KHÔNG làm:**
- **Không tự quyết ACL/quyền.** `document_ids` do query-service (MCP client) lọc sẵn và inject; tool chỉ dùng đúng những gì được truyền vào.
- Không rewrite query (việc đó ở phía agent/query-service).
- Không gọi LLM trả lời cuối — chỉ trả chunk để query-service đưa vào prompt.
- Không ghi DB; chỉ đọc Qdrant (qua rag-worker contract).

**Ranh giới dữ liệu:** đọc collection vector của rag-worker; fail-closed nếu collection/dimension/fingerprint lệch.

## Plan

- [x] Định nghĩa runtime contract: tool `rag_search(query, document_ids?, top_k=5)`.
- [x] Output shape ổn định: `chunk_id`, `document_id`, `document_name`, `caption`, `parent_text`, `heading_path`, `score`, `page_number`, `source_gcs_uri`, `markdown_gcs_uri`.
- [x] Reranker pluggable: `none` / `lexical` / `llm`, fallback an toàn khi rerank lỗi.
- [x] Startup fail-closed: `verify_contract()` chạy trước khi serve.
- [x] Internal token auth (`X-Internal-Token`) cho endpoint MCP.
- [x] e2e CI rag-worker → mcp xanh.

## Implement

- Tool đăng ký tại `app/interfaces/mcp_server.py` (`@mcp.tool() rag_search`), transport Streamable HTTP, endpoint mặc định `http://localhost:8003/mcp`.
- Logic search ở `app/core/search.py` (`SearchService` / `build_search_service`); embedding `app/core/embedding.py`; rerank `app/core/rerank.py`; vector store `app/core/vectorstore.py`.
- Reranker hỗ trợ `none`, `lexical`, `llm`. Nếu `llm` lỗi/timeout → fallback `NoopReranker` (giữ thứ tự vector score), không làm vỡ `rag_search`. Lưu ý: fallback là best-effort, có thể trả hit dưới ngưỡng rerank.
- Auth: `InternalTokenAuthMiddleware` so khớp header `X-Internal-Token` (bật khi token được cấu hình).
- Config host/port qua `MCP_HOST` / `MCP_PORT`.

> Chi tiết tham chiếu: [../README.md](../../README.md), [docs/mcp-query-integration.md](../../../../docs/mcp-query-integration.md).
