---
title: Hợp đồng liên-service — tóm tắt & con trỏ
last-verified: 59551e39 (2026-06-29)
code-refs:
  - docs/contracts.md
  - infra/nats/{subjects.md,event-contracts.yaml}
  - infra/ci/*.py
---

# Hợp đồng (contracts) — bản 1 trang

Trang này KHÔNG lặp lại nội dung hợp đồng; nó TRỎ tới nguồn sự thật và nêu nguyên tắc.
Chi tiết từng hợp đồng (đã verify từ code): xem thư mục **[docs/contracts/](../contracts/)** —
[sse-contract](../contracts/sse-contract.md) · [api-spec](../contracts/api-spec.md) ·
[nats-events](../contracts/nats-events.md) · [jwt-claims](../contracts/jwt-claims.md) ·
[embed-models](../contracts/embed-models.md).

## Nguyên tắc single-source

Mỗi seam liên-service có **1 nguồn sự thật + linter AST trong CI** chặn drift ÂM THẦM (không compile-error, không test đơn nào đỏ) trước khi ra prod.

| Seam | Nguồn sự thật | Tài liệu người đọc |
|---|---|---|
| NATS events | `infra/nats/event-contracts.yaml` | [contracts/nats-events.md](../contracts/nats-events.md) |
| JWT claims | `infra/auth/jwt-claims-contract.yaml` | [contracts/jwt-claims.md](../contracts/jwt-claims.md) |
| HTTP hr-service | `infra/http/hr-service-contract.yaml` | [contracts/api-spec.md](../contracts/api-spec.md) |
| MCP tool result | `infra/mcp/tool-result-contract.yaml` | [services/mcp-service.md](../services/mcp-service.md) |
| Embed model registry | embeddings.yaml + contract.py + routing.yaml + catalog | [contracts/embed-models.md](../contracts/embed-models.md) |
| SSE chat contract | `query-service/app/agents/sse_contract.py` | [contracts/sse-contract.md](../contracts/sse-contract.md) |
| Alembic migration | chuỗi revision mỗi service | [ops/runbook.md](../ops/runbook.md) |

## 7 CI gate (infra/ci/)

Tất cả thuần tĩnh (AST/diff, không cần DB/hạ tầng); lệch = exit 1, đỏ trước deploy.

| Gate | File | Chặn lỗi gì |
|---|---|---|
| NATS | `nats_contract_lint.py` | publisher/consumer + subjects.md lệch event-contracts.yaml (bỏ/đổi field → consumer xử sai / NAK-storm) |
| JWT | `jwt_claims_lint.py` | producer (user-service) ↔ consumer (query/doc/hr) lệch claims → ACL sai |
| HTTP | `http_contract_lint.py` | client dict thô lệch Pydantic hr-service → 422 lúc chạy (vỡ luồng đơn nghỉ) |
| MCP result | `mcp_result_lint.py` | mcp đổi field shape → query parse khoan dung → mất nguồn/citation âm thầm |
| Embed model | `embed_model_lint.py` | drift embed model rag-worker ↔ ai-router → multi-collection giả (bug qwen8b 2026-06-28) |
| Migration | `migration_lint.py` | trùng revision id / down_revision treo / nhiều head / cycle |
| Schema drift | `schema_drift_check.py` | code đọc bảng (vd `user_access_profile`) không có migration → "relation does not exist" (sự cố 2026-06-16) |

## Bất biến chính (đừng phá)

- **SSE done-event**: `session_id` + `sources` (array) + `ref` (int) + `phase` values — sửa query-service không được làm vỡ FE chat.
- **doc.status** là kênh DUY NHẤT cập nhật `documents.status`; rag-worker KHÔNG ghi `doc_db`.
- **Tham số nhạy cảm** (`document_ids`, `user_id`, `approver_user_id`) luôn inject từ JWT, không tin LLM.
- **Database-per-service**: không service nào đọc thẳng DB của service khác; chỉ qua event/HTTP.
- Thay đổi contract = sửa **nguồn sự thật** (file trong bảng trên) → Dev update impl → CI gate xanh → merge. Không sửa tài liệu người đọc thay cho nguồn.
