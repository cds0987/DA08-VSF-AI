# NEW_REPO_DECISIONS — Quyết định của repo production

> **Viết tay, cập nhật mỗi khi có quyết định kiến trúc mới khác prototype.** Dùng format Decision Log như [MINDSET.md](./MINDSET.md) Section 3.
>
> File này ghi những gì repo production làm *khác* prototype và *tại sao*. Là phần mở rộng *sống* của bundle: MINDSET/CONSTRAINTS/LESSONS đóng băng tư duy prototype; file này ghi tư duy production.
>
> Các quyết định *bắt buộc phải chốt trước commit đầu* được liệt kê (chưa quyết) ở [DAY0_CHECKLIST.md](./DAY0_CHECKLIST.md). Khi chốt một mục day-0, ghi kết quả vào đây dưới dạng một block.

---

## Cách dùng

Mỗi quyết định = một block theo template dưới. Không xóa quyết định cũ — nếu đảo, thêm block mới tham chiếu block cũ ("Thay thế D# ngày ...").

Một quyết định chỉ được xem là hợp lệ khi có:

- status rõ ràng (`PROPOSED` hoặc `RATIFIED`)
- người chốt cụ thể khi ratified
- lý do chọn trong bối cảnh repo mới
- trade-off phải chấp nhận
- điều kiện xem xét lại

Không dùng file này để chép lại quyết định của prototype như thể repo mới đã chốt. Prototype là nguồn học, không phải authority của repo production mới.

```
### D#. [Tên quyết định]
**Status:** PROPOSED | RATIFIED YYYY-MM-DD (ai chốt)
**Khác prototype ở:** [prototype làm gì → repo này làm gì]
**Vấn đề cần giải quyết:** [tình huống cụ thể]
**Options đã cân nhắc:**
- A: [tên] — [lý do không chọn]
- B (đã chọn): [tên] — [lý do chọn]
**Trade-off phải chấp nhận:** [cái gì bị hy sinh]
**Khi nào nên xem xét lại:** [điều kiện cụ thể]
**Ràng buộc mới phát sinh:** [nếu có → thêm vào CONSTRAINTS.md]
```

---

## Quyết định

<!--
Trống cho đến khi repo production chốt quyết định đầu tiên.

Gợi ý: các mục trong DAY0_CHECKLIST.md là ứng viên trở thành D1, D2, ... ở đây.
Khi một mục day-0 được team chốt (RATIFIED), copy thành một block theo template trên,
ghi rõ người chốt + ngày + lý do chọn trong bối cảnh repo mới (không phải bối cảnh prototype).

Đừng dán sẵn quyết định của prototype vào đây như thể repo mới đã chốt —
bối cảnh, stack, ràng buộc của repo mới có thể khác. Để team quyết, rồi mới ghi.
-->
