# AI làm sai gì — và mình chỉnh thế nào

Rút từ memory (feedback) + các lần mình sửa Claude khi làm. Mục đích: học cách **làm việc với AI**,
không chỉ học code. AI cày được khối lượng lớn + trace sâu, nhưng hay **kết luận vội** và **đi tắt** —
phần lớn giá trị nằm ở chỗ mình ra nguyên tắc + bắt đo lại.

---

## A. Sai về HÀNH VI (cách làm) — mình ra nguyên tắc để chặn trước

| AI làm sai | Mình chỉnh | Nguyên tắc đọng lại |
|---|---|---|
| Tự phát / đi tắt / hardcode model, giá trị | Bắt dẹp hardcode + gate drift xuyên-service; pattern thiếu thì **MỞ RỘNG** đúng cách, không bypass | *no-rogue*: MOSA + OOP + no-hardcode, mọi call qua AI-Router |
| Suýt làm **vỡ hợp đồng SSE** của FE khi sửa query-service | Giữ bất biến done-event (`session_id` + `sources[]` + `ref` int + phase); thêm node phải khai contract (CI đỏ nếu thiếu) | Đụng query-service không được vỡ FE chat |
| Định **bỏ test khỏi CD** cho nhanh | "Đừng bỏ — test đã từng cứu sự cố"; phân tầng smoke thay vì cắt | CD giữ test, smoke phân tầng |
| Tìm thấy lỗi trong test campaign là **định fix ngay** | "Plan fix chờ duyệt mới fix" (phân tầng P0–P3) | Không tự ý sửa rộng — duyệt trước |
| Commit/branch cẩu thả, dễ đè mất commit người khác | Luôn merge latest, không mất/đè; thao tác huỷ cần duyệt | develop: admin làm trực tiếp, merge an toàn |
| Quên eval khi push code | "Mỗi lần push kèm `systemeval/` + commit `queryeval/`" | Eval đi cùng nhịp code |

## B. Sai về CHẨN ĐOÁN (kết luận vội / đọc sai số) — mình bắt đo lại

1. **"pplx model chậm 2687ms"** → kết luận từ **median 3 mẫu** (nhiễu). Mình nghi → đo lại 8× →
   pplx thật ~542ms, *mọi* model đều có đuôi (tail) nặng.
   → **Học:** 3 mẫu không đủ; phải nhiều mẫu + nhìn phân phối, không nhìn 1 con số.

2. **"embed bị saturation do tải"** → mình hỏi *"có batch mà?"* → AI nhìn lại: `EMBED_BATCH_SIZE=100`,
   158 chunk = **2 call** chứ không phải 158.
   → **Học:** hiểu cơ chế batch trước khi đổ lỗi cho tải.

3. **"no_inflight_cap đã fix 503"** → vẫn lỗi. Gốc thật: `est = SUM(batch)` ~8300 token > ctx bge-m3
   8192 → `feasible_model` loại sạch. Mình hỏi *"lạ vậy, đưa vào 1 list nhiều câu mà?"* → đổi
   `est = MAX(per-text)`.
   → **Học:** ước lượng token theo **per-text**, không phải tổng cả batch.

4. **"sức chứa chỉ 200–300 user"** → mình bác: 1200 user = `1200/4/60 = 5 q/s` thôi, mà test đã chạy
   **7.5 q/s** (nặng gấp đôi). AI đặt thước UX<5s — kiến trúc có **sàn ~7s/câu** nên thước đó phi thực tế.
   Tính lại Little's Law (`in-flight = QPS × latency`): hệ **thừa sức 1200**, giới hạn là *latency* không
   phải số user.
   → **Học:** quy đổi tải cho đúng; đừng đặt thước UX mà kiến trúc không bao giờ đạt.

5. **//hóa model + chunk-180** = "tối ưu theo cảm giác" → số liệu bác (xiaomi p99 15s kéo tail xấu;
   recall 0.944→0.873) → **revert**.
   → **Học:** đo trước, chỉ giữ cái có số chứng minh.

## C. Sai về QUY TRÌNH (thao tác) — mình chỉnh ngay lúc đó

1. **Restart benchmark từ đầu** khi mình muốn chạy tiếp → *"ko chạy lại từ đầu, chạy tiếp"* → làm
   **resumable** (skip câu đã xong, append). → Việc dài phải resumable, đừng phá tiến độ.
2. **Concurrency cao gây nghẽn** lúc đo baseline → *"vừa phải 4 để tránh nghẽn"*. → Baseline phải thật ít tải.
3. **Rò corpus mật lên GitHub** do `.gitignore` append lỗi (dòng bị nối liền) → reset + untrack going-forward.
   → Kiểm `.gitignore` sau khi sửa; corpus mật không bao giờ commit.
4. **Định đọc/SSH prod tùy tiện** → bị chặn, cần mình **duyệt rõ target**. → Prod read/write cần phép tường minh.

## Kết — cách mình lái AI cho đúng
- **Cho nguyên tắc trước**: code = bằng chứng · no-hardcode · no-rogue · đo trước khi tối ưu · duyệt trước khi sửa rộng.
- **Bắt đo lại** khi kết luận đáng ngờ; hỏi *"có chắc không / cơ chế thế nào / sao biết"*.
- **Lưu feedback vào memory** để AI không lặp lại lỗi cũ.
- AI là cặp tay cày + trace; **quyết định cuối vẫn là mình**, dựa trên số liệu thật.

> Xem chi tiết kỹ thuật từng commit ở [week1](week1.md)–[week5](week5.md); dòng thời gian ở [README](README.md).
