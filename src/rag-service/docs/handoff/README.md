# Handoff — Mindset Transfer Bundle

Thư mục này chuyển *engineering intent* từ prototype sang một repo production mới. Đọc trước khi đọc hoặc viết code.

Bundle tách thành: bài học ổn định, ràng buộc cứng, và một checklist day-0. `NEW_REPO_DECISIONS.md` cố ý để trống như file *sống* cho các quyết định của repo production.

Toàn bộ bundle viết ở mức **transferable**: nêu ý tưởng theo *vai trò*, không cột vào tên thư mục/class/stack của prototype. Chỗ `Trong prototype:` chỉ là minh hoạ một lần hiện thực — tham khảo, không phải ràng buộc.

| File | Trả lời | Đọc khi nào |
|---|---|---|
| [PORTING_GUIDE.md](./PORTING_GUIDE.md) | Bê bundle này sang repo mới như thế nào cho đúng | Ngay sau khi copy thư mục |
| [MINDSET.md](./MINDSET.md) | *Tại sao* các lựa chọn kiến trúc có ý nghĩa | Đầu tiên — để căn chỉnh design judgment |
| [DAY0_CHECKLIST.md](./DAY0_CHECKLIST.md) | Phải chốt gì trước commit production đầu tiên | Ngay sau MINDSET |
| [CONSTRAINTS.md](./CONSTRAINTS.md) | Ràng buộc nào không được vi phạm | Trước khi viết/sửa code |
| [LESSONS.md](./LESSONS.md) | Đã thử gì, fail gì, đúng gì, lần sau làm khác gì | Trước khi lặp lại một approach |
| [NEW_REPO_DECISIONS.md](./NEW_REPO_DECISIONS.md) | Repo production *cố ý khác* prototype ở đâu | Cập nhật liên tục bởi repo mới |

## Trạng thái transfer

Bundle này **sẵn sàng để dùng làm seed cho Day 0 của repo mới**, không phải bản thiết kế production đã chốt sẵn. Repo mới được phép khác prototype, nhưng mọi điểm khác biệt có ảnh hưởng đến runtime, dữ liệu, bảo mật, chi phí, hoặc contract với consumer phải được ghi vào [NEW_REPO_DECISIONS.md](./NEW_REPO_DECISIONS.md).

Không dùng bundle này như danh sách file cần copy từ prototype. Dùng nó như danh sách quyết định cần hiểu, chốt, hoặc cố ý thay đổi.

## Source Material

`MINDSET.md`, `CONSTRAINTS.md`, `LESSONS.md`, `DAY0_CHECKLIST.md` được distill từ prototype DE Vector Search Engine:

- `docs/ARCHITECTURE.md`
- `docs/AGENTS.md`
- `docs/PIPELINE.md`
- `docs/RISKS.md`
- `docs/STATUS.md`
- `docs/notes/*`
- runtime code trong `app/`, `api/`, `utils/`, `adapters/`
- lịch sử legacy recover được từ git

Quy ước: chỗ nào suy luận intent của tác giả (không viết nguyên văn trong nguồn) đánh dấu `[INFERRED]`.

Các source material ở trên chỉ là audit trail. Repo mới không cần copy toàn bộ source material để bắt đầu, nhưng nếu một quyết định gây tranh luận thì phải tra lại source tương ứng hoặc ghi rõ vì sao repo mới chọn khác.

## Thứ tự đọc

1. Đọc `PORTING_GUIDE.md` để biết cách đưa bundle vào repo mới.
2. Đọc `MINDSET.md` để hiểu intent về sản phẩm và kiến trúc.
3. Đọc `DAY0_CHECKLIST.md` trước khi scaffold code.
4. Đọc `CONSTRAINTS.md` trước khi implement.
5. Đọc `LESSONS.md` trước khi chọn một approach giống thứ đã từng thử.
6. Ghi các lựa chọn riêng của production vào `NEW_REPO_DECISIONS.md`.

## Luật cho dự án mới

Không bắt đầu implement cho đến khi các mục day-0 *được quyết* hoặc *hoãn có chủ đích* (có owner + điều kiện revisit). Những lỗi đắt nhất ở prototype đều đến từ việc coi các mục này là chi tiết điền sau (đây là các mục đại diện; **danh sách đầy đủ + trạng thái ở [DAY0_CHECKLIST.md](./DAY0_CHECKLIST.md)**):

- async-native vs sync-có-executor-riêng
- production fallback policy
- migration flow
- atomic claim & terminal-status
- queue restart recovery
- optional dependency policy
- observability baseline
- delivery/rollout verification
- runtime config compatibility
- pipeline quality/evaluation gate
- data retention & artifact lifecycle
- cost/budget guardrail

## Không copy nguyên từ prototype

Những thứ sau là dấu vết đã học được từ prototype, không phải pattern để lặp lại:

- không copy mô hình async nửa vời: edge async nhưng I/O blocking bị đẩy bừa vào threadpool chung
- không copy default cho phép mock/in-memory/file fallback ở production
- không coi in-memory queue là cơ chế bền qua restart
- không copy claim kiểu đọc-rồi-ghi không lock
- không để terminal status update thiếu claim id/run id
- không để lớp compat/legacy nằm trên runtime path chính
- không coi test in-memory là bằng chứng cho semantics của backend production
- không coi CI xanh là bằng chứng production đang chạy code mới
- không đổi provider/model/dimension như config rời rạc thiếu validation
- không tạo bảng/index/log mới nếu chưa biết ai đọc và retention thế nào
