# MCP Service — Tiến độ & việc cần làm

**Trạng thái:** 🟢 Production, verified `CallToolRequest` thật · **Mức hoàn thiện:** ~85% · **Cập nhật:** 2026-06-12
**Vai trò:** MCP server — tool `rag_search` (search Qdrant) + `hr_query` (proxy HR). Service **độc lập**, tự dựng hạ tầng riêng, ghép với RAG chỉ qua Qdrant URL. **KHÔNG dùng chung `core_engine`.**

## Đã ổn định (căn bản XONG)
- ✅ **Tool `rag_search`** (search-only): đọc Qdrant, embed query, rerank top-k, trả chunk metadata (`chunk_id`, `document_id`, `caption`, `parent_text`, `score`, `page_number`, …) để query-service cite nguồn.
- ✅ **Fail-closed startup:** `verify_contract()` chạy trước khi serve — collection/dimension/fingerprint lệch với rag-worker thì thoát sớm.
- ✅ **Reranker** `none` / `lexical` / `llm` với fallback an toàn về `NoopReranker` (best-effort, không vỡ `rag_search`).
- ✅ **Tool `hr_query` (proxy):** HTTP proxy sang hr-service (`POST /hr/query`, header `X-Internal-Token`). MCP **không sở hữu HR data**. Mặc định TẮT (`TOOL_HR_QUERY_ENABLED=0`). 7 intent: `leave_balance / leave_requests / attendance / onboarding / payroll / benefits / performance`.
- ✅ **Config nest theo tool** + enabled policy + cache discovery.
- ✅ **CI integration thật (Docker):** workflow e2e hr+mcp với payroll exposed + soft-404.
- ✅ **Verified production (06-10):** thấy `CallToolRequest` thật — `rag_search` + `hr_query` execute thật, trả 5 kết quả score 0.62–0.67.

## Việc cần làm để vào Production thật

### 🟡 Trung bình
- [ ] **Tool WRITE `create_leave_request`** — thiết kế xong (`src/mcp-service/docs/maintool/`), feature-flag OFF mặc định, **chưa code**. Cần phối hợp với HR Service (#5 roadmap). Cần SA approve contract trước.
- [ ] **Security hardening** — theo `src/mcp-service/docs/security-hardening.md`: rà soát auth giữa MCP ↔ hr-service (`X-Internal-Token`), giới hạn tool theo enabled policy khi lên production thật.

## Lưu ý vận hành / bẫy đã biết
- MCP là service độc lập — đừng cố ghép chung engine với rag-worker; chỉ ghép qua **Qdrant URL**.
- ✅ **`top_k` đã đủ headroom (06-12):** query-service nâng `rag_top_k=8` (trần 10); mcp `top_k_candidates=20`, `final_k=min(requested, 20)` → trả đủ 8, KHÔNG cắt. Chỉ rơi về `rerank_top_k=3` khi query-service không truyền `top_k`. Không cần nới thêm. (xem `src/query-service/Docs/bug.md` #4)
- `hr_query` mặc định TẮT — khi bật phải đảm bảo hr-service đã có seed data (xem [03-hr-service.md](03-hr-service.md)) nếu không trả 404 → NO_INFO.
- Tool WRITE phải: backward-compatible, feature-flag OFF, NATS best-effort (không fail-closed).

## Liên kết
- Roadmap tổng: [00-roadmap.md](00-roadmap.md)
- Thiết kế tool WRITE: [../../src/mcp-service/docs/maintool](../../src/mcp-service/docs/maintool)
- Security: [../../src/mcp-service/docs/security-hardening.md](../../src/mcp-service/docs/security-hardening.md)
