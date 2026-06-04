# PORTING_GUIDE — Cách chuyển handoff sang repo mới

> **Mục đích:** Biến bundle handoff thành quy trình khởi động repo mới. Đây không phải hướng dẫn copy code prototype. Đây là checklist để tránh mang theo nợ kỹ thuật cũ.

---

## 1. Sau khi copy thư mục

Làm các bước này trước khi scaffold code:

- kiểm tra tất cả file Markdown hiển thị đúng tiếng Việt trên GitHub, VS Code, và terminal
- giữ encoding là UTF-8
- đọc [README.md](./README.md), [MINDSET.md](./MINDSET.md), rồi [DAY0_CHECKLIST.md](./DAY0_CHECKLIST.md)
- đổi từng mục Day 0 sang trạng thái `DECIDED` hoặc `DEFERRED`
- ghi mọi quyết định đã chốt vào [NEW_REPO_DECISIONS.md](./NEW_REPO_DECISIONS.md)
- nếu repo mới cố ý khác prototype, ghi lý do khác ngay lúc quyết định, không để ghi sau

Không bắt đầu implementation production đầu tiên khi [NEW_REPO_DECISIONS.md](./NEW_REPO_DECISIONS.md) vẫn trống mà [DAY0_CHECKLIST.md](./DAY0_CHECKLIST.md) chưa có mục nào được chốt.

## 2. Quy tắc chốt và hoãn quyết định

Mỗi quyết định Day 0 phải có một trong hai trạng thái:

- `DECIDED`: đã chọn hướng làm, có trade-off, có điều kiện xem xét lại
- `DEFERRED`: cố ý hoãn, có owner, có ngày hoặc điều kiện buộc phải revisit

Không dùng trạng thái "để sau tính" cho các mục ảnh hưởng đến dữ liệu, runtime, bảo mật, chi phí, hoặc contract với consumer.

Người chốt quyết định phải được ghi rõ trong [NEW_REPO_DECISIONS.md](./NEW_REPO_DECISIONS.md). Nếu chưa có owner, quyết định đó chưa được xem là hợp lệ.

## 3. Những gì được copy từ prototype

Được copy ý tưởng và invariant:

- retrieval unit là đơn vị có nghĩa, không phải chunk kỹ thuật
- embedding unit có thể khác retrieval payload
- canonical artifact giúp reprocess rẻ hơn
- id deterministic giúp reprocess idempotent
- contract + adapter giữ business không phụ thuộc SDK
- health phải phản ánh degraded state thật
- production phải fail-closed với backend chính

Không được copy code chỉ vì nó đang chạy trong prototype. Mọi code được copy phải đi qua lại các ràng buộc trong [CONSTRAINTS.md](./CONSTRAINTS.md).

## 4. Những gì không được copy từ prototype

Không bê các lựa chọn này sang repo mới như mặc định:

- async nửa vời: handler async nhưng I/O blocking dùng chung threadpool
- fallback im lặng sang mock, in-memory, hoặc file ở production
- queue chỉ nằm trong memory nhưng được hiểu như durable queue
- claim đọc-rồi-ghi thiếu lock hoặc thiếu conditional update
- terminal status update không gắn với claim id/run id hiện hành
- factory hoặc adapter chính import từ lớp compat/legacy
- SDK optional import ở top-level làm test suite crash khi thiếu dependency
- test chỉ chạy trên in-memory rồi kết luận backend thật đúng semantics

Nếu buộc phải dùng tạm một lựa chọn trong danh sách này, phải ghi rõ trong [NEW_REPO_DECISIONS.md](./NEW_REPO_DECISIONS.md): vì sao tạm chấp nhận, rủi ro là gì, khi nào phải thay.

## 5. Definition of Ready trước khi code production

Repo mới chỉ sẵn sàng viết code production đầu tiên khi các điều kiện này đúng:

- Day 0 runtime model đã được chốt hoặc defer có owner
- migration loop đã có đường chạy tối thiểu
- fallback policy production đã rõ
- queue recovery policy đã rõ
- atomic claim và terminal status semantics đã rõ
- health contract tối thiểu đã rõ
- optional dependency policy đã rõ
- observability baseline đã rõ
- pipeline acceptance/evaluation gate đã rõ

Nếu một mục chưa rõ, vẫn có thể viết spike hoặc prototype nội bộ, nhưng không gọi đó là production foundation.

## 6. Definition of Done cho transfer

Transfer được xem là hoàn tất khi:

- [ ] tất cả file trong `docs/handoff` render đúng tiếng Việt
- [ ] [DAY0_CHECKLIST.md](./DAY0_CHECKLIST.md) có trạng thái cho từng mục
- [ ] [NEW_REPO_DECISIONS.md](./NEW_REPO_DECISIONS.md) có ít nhất các quyết định đã chốt cho Sprint 1
- [ ] mọi quyết định khác prototype đều có lý do và trade-off
- [ ] mọi external reference cần thiết đã được copy, thay bằng summary, hoặc ghi rõ là audit-only
- [ ] team mới biết rõ phần nào là constraint cứng và phần nào là lựa chọn có thể thay
