# Nguyen Working — Sổ tay phụ trách 3 service

**Người phụ trách:** Nguyen Tran · **Branch làm việc:** `nguyendev` (PR → `develop` → deploy VM)
**Cập nhật:** 2026-06-12

Folder này là khu vực làm việc cá nhân theo dõi tiến độ và lộ trình **đưa 3 service chính vào production thật**:

| Service | Vai trò ngắn | File chi tiết |
|---------|--------------|---------------|
| **RAG Worker** | Subscriber NATS — ingest (OCR/chunk/embed) → Qdrant | [01-rag-worker.md](01-rag-worker.md) |
| **MCP Service** | MCP server — tool `rag_search` + `hr_query` | [02-mcp-service.md](02-mcp-service.md) |
| **HR Service** | API nội bộ — employee profile + 7 intent HR | [03-hr-service.md](03-hr-service.md) |

> **Phạm vi quyền:** ngoài 3 service trên, tôi được phép **đụng vào `query-service`** (đảm bảo 3 service chạy thông với agent LangGraph). Các service khác (frontend, user, document) coi như ngoài phạm vi trừ khi cần phối hợp.

## Điều hướng nhanh
- **Tổng quan tiến độ + ưu tiên toàn cục:** [00-roadmap.md](00-roadmap.md) ← đọc cái này trước
- **Hướng dẫn dev (cách code + viết test chặt, tránh vỡ codebase):** [dev.md](dev.md) ← dev mới đọc cái này
- **Trace & debug rag-worker bằng Langfuse (biết crash ở đâu):** [rag-worker-langfuse.md](rag-worker-langfuse.md)
- **Định nghĩa "Production-Ready":** [04-definition-of-done.md](04-definition-of-done.md)
- **Refactor DB migration (doc/user → Alembic) + cơ chế đồng bộ danh tính:** [05-db-migration-va-dong-bo.md](05-db-migration-va-dong-bo.md)
- **Đồng bộ data tồn đọng (việc còn lại — đọc kỹ trước khi làm):** [06-dong-bo-data-ton-dong.md](06-dong-bo-data-ton-dong.md)

## Quy ước
- Mọi mốc relative date đổi sang absolute (vd "tuần sau" → ghi ngày cụ thể).
- Mỗi lần đẩy 1 việc vào production phải tick checklist trong [04-definition-of-done.md](04-definition-of-done.md).
- Nguồn dữ liệu gốc: [../BAO_CAO_TIEN_DO_rag-mcp-hr.md](../BAO_CAO_TIEN_DO_rag-mcp-hr.md), git log theo service, README từng service.
