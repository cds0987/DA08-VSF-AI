# UI Review tự động bằng Playwright (Chromium headless)

> Quy trình "tự lái trình duyệt" để review toàn bộ tính năng FE + full RAG flow trên VM
> production, bắt lỗi JS/console/network thay cho mở F12 thủ công.
> Script: [tmp-ui-check/ui_check.py](tmp-ui-check/ui_check.py) (+ các `q*.py`, `verify_rag*.py`).

---

## 1. Mục đích

- Mở Chromium headless qua **Playwright** vào FE thật trên VM (`http://34.158.47.236`).
- Đăng nhập admin + chat, đi qua mọi route, **chụp screenshot full-page** từng trang.
- Thu thập tự động 3 nhóm lỗi gắn theo trang đang xem:
  - **PAGE ERRORS** — uncaught JS (`pageerror`).
  - **CONSOLE ERRORS** — `console.error` (`console` type=error).
  - **NETWORK ≥400** — response status ≥ 400 (bỏ asset: favicon, `/_nuxt/`, `.css`, `.js.map`, `.woff`).
- Chạy **full RAG flow** end-to-end qua UI: upload tài liệu → hỏi chatbot → chờ câu trả lời RAG.

## 2. Cách chạy

```bash
pip install playwright
playwright install chromium
python tmp-ui-check/ui_check.py
```

Output đổ vào `tmp-ui-check/`:
- `report.txt` — tổng hợp lỗi theo trang.
- `<page>.png` — screenshot từng bước (admin-login, admin-dashboard, admin-documents,
  admin-audit, admin-users, admin-upload, admin-upload-done, chat-login, chat-answer, …).

## 3. Thông số mặc định (sửa trong script)

| Biến | Giá trị |
|---|---|
| `BASE` | `http://34.158.47.236` (VM production) |
| `EMAIL` / `PASSWORD` | `admin@company.com` / demo admin password |
| `UPLOAD_FILE` | `src/rag-worker/eval/validation/leave_policy.md` |
| Viewport | 1366×900, `ignore_https_errors=True`, headless |

## 4. Các bước script đi qua

1. **Admin**: `/admin/login` → điền email/password → submit → chụp sau login.
2. Duyệt lần lượt: `/admin/` (dashboard), `/admin/documents`, `/admin/audit`, `/admin/users`, `/admin/upload`.
3. **Upload flow**: chọn file vào `input[type=file]` → click `Upload All`/`Upload`/submit → chờ → kiểm body có chuỗi `indexed`.
4. **Chat (full RAG)**: `/login` → đăng nhập → gõ câu hỏi `"Nhân viên được bao nhiêu ngày phép năm?"` → Enter/Send → chờ ~12s câu trả lời → chụp `chat-answer.png`.

Mỗi lần `goto` dùng `wait_until="networkidle"`, timeout 45s, rồi screenshot full-page.

## 5. Tiêu chí PASS

Báo cáo "sạch" khi cả 3 nhóm = 0 (xem [tmp-ui-check/report.txt](tmp-ui-check/report.txt)):

```
PAGE ERRORS (uncaught JS): 0
CONSOLE ERRORS: 0
NETWORK >=400 (bỏ asset): 0
```

Kết hợp kiểm bằng mắt qua screenshot + xác nhận chat-answer.png có câu trả lời RAG đúng ngữ cảnh.

## 6. Script phụ trợ

- `verify_rag.py` / `verify_rag2.py` — kiểm riêng RAG retrieval qua API/UI.
- `q.py … q6.py` — các truy vấn thử nghiệm rời để soi nhanh từng câu hỏi.

## 7. Quan hệ với CI/CD

Đây là **kiểm chứng thủ công/bán tự động sau deploy** (smoke sâu hơn). CI ([CICD.md](CICD.md))
chỉ smoke nội dung tĩnh qua nginx (`__NUXT`/placeholder). UI review Playwright bổ sung lớp
kiểm **hành vi động + full RAG flow thật** mà smoke CI không phủ.
