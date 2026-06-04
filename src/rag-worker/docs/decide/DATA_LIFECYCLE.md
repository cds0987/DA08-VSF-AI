# Data Lifecycle — rag-service

> Mục tiêu: chốt bảng "loại dữ liệu → owner → retention → cleanup" cho các storage path
> hiện có trong repo, để tránh write-only storage và retention mơ hồ.
>
> Trạng thái: **RATIFIED 2026-06-04** cho phạm vi hiện tại của repo.

---

## Bảng lifecycle

| Loại dữ liệu | Owner | Mục đích / consumer | Retention | Cleanup |
|---|---|---|---|---|
| `documents` metadata row | rag-service | `GET /api/ingest`, trạng thái ingest, chunk_count, failure reason | Giữ cho đến khi document bị xoá hoặc được migrate sang store khác | `DELETE /api/ingest/{document_id}` xoá row; về sau cần reconcile orphan khi có source-of-truth ngoài service |
| `job_logs` audit row | rag-service | debug ingest lifecycle, audit failure, retention runner | Mặc định `JOBLOG_RETENTION_DAYS=30` | Runtime background pruner gọi `prune_job_logs_older_than(...)` mỗi `JOBLOG_PRUNE_INTERVAL_SECONDS` |
| Vector index / collection | rag-service | search retrieval | Giữ cho đến khi document bị xoá hoặc diễn ra reindex/model migration | `delete_by_document(document_id)` khi xoá document; reindex/migration phải cutover sang index mới rồi dọn index cũ |
| In-process vector data (`:memory:`) | dev/test only | local smoke test, offline development | Chỉ sống cùng process | Tự mất khi process dừng; **không** là production storage |
| Canonical artifact | chưa có trong repo | chưa có consumer runtime vì parser/artifact pipeline chưa được implement | Chưa áp dụng | Khi implement parser phải chốt prefix, owner, retention và cleanup trước khi merge |
| Raw source bytes | caller / upstream system | rag-service hiện chỉ nhận markdown đã parse sẵn | Ngoài phạm vi repo hiện tại | Không lưu trong rag-service; policy thuộc caller/upstream |

---

## Quyết định vận hành

- `job_logs` là **audit best-effort**, không được chặn ingest path chính.
- `JOBLOG_RETENTION_DAYS` và `JOBLOG_PRUNE_INTERVAL_SECONDS` là startup config bắt buộc hợp lệ.
- Production không được chạy với metadata backend in-memory.
- Bất kỳ storage path mới nào cũng phải cập nhật bảng này trước khi merge.

---

## Phần còn mở

- Khi parser/canonical artifact được thêm, phải cập nhật file này với:
  - artifact owner
  - artifact retention
  - cleanup path cho reindex / source delete / orphan reconcile
- Khi có source-of-truth ngoài service, cần quyết định orphan policy cho `documents`.
