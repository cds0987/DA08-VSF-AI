# load20 — đo chất lượng UI thật dưới 20 concurrent user

Mục tiêu: với **20 user đồng thời** trên prod (vsfchat.cloud), đo cái user *thật sự cảm nhận*:
TTFT (tới token trả lời đầu), độ đều token (giật/khựng), độ công bằng giữa user, và mức
degrade (save_mode/429) — đối chiếu với **VM log của ai-router** (chỉ đọc).

## Vì sao thiết kế thế này

- **Cap 3 SSE/user** (`query_max_concurrent_per_user=3`) ⇒ KHÔNG thể 20 phiên trên 1 account.
  → seed **20 user riêng**, mỗi user 1 phiên ⇒ đúng nghĩa "20 user".
- **Hybrid**: 4 trình duyệt Playwright THẬT (đo nhịp gói qua Cloudflare/nginx — bắt buffering proxy,
  đúng thứ user thấy) + 16 phiên SSE-HTTP nhẹ (timestamp token chính xác). Đủ tải 20, máy không sập.
- **Barrier**: cả 20 bắn `/query` cùng một thời điểm ⇒ tái hiện burst (đúng lúc AIMD còn trần thấp).

## Chạy

```bash
# 0) cần mạng tới prod (wifi công ty có thể chặn SSE — xem memory proxy-domain-blocks-sse, đổi mạng)
# 1) seed 20 user test (idempotent; admin tạo qua POST /api/user/users)
python eval/load20/seed_users.py

# 2) chạy load-test (in report + lưu eval/load20/out/run_<ts>/)
python eval/load20/run_load20.py

# 3) đối chiếu VM log trong cửa sổ test (read-only; chạy từ máy user)
bash eval/load20/pull_vm_logs.sh '<window_start_utc>' '<window_end_utc>'
```

## Tham số (env, tùy chọn)

| env | mặc định | nghĩa |
|---|---|---|
| `LOAD_N_USERS` | 20 | tổng user đồng thời |
| `LOAD_N_BROWSERS` | 4 | số phiên dùng trình duyệt thật (còn lại là SSE) |
| `LOAD_BASE` | https://vsfchat.cloud | target |
| `LOAD_USER_PW` | LoadTest123! | mật khẩu user test |
| `LOAD_ADMIN_EMAIL/PW` | (repo default) | admin để seed |

## Đọc kết quả (report.md)

- **TTFT-answer p50/p95**: trễ tới token trả lời đầu. p95 cao = đuôi xấu (tail latency).
- **Độ đều token gap p95 + maxstall**: gap nhỏ & ổn = mượt; stall>2s = UI khựng (proxy buffer / event-loop nghẽn).
- **Công bằng CV**: >0.5 nghĩa một số user bị bỏ đói (head-of-line trên 1 event-loop ai-router).
- **Degrade save_mode**: >0 ⇒ pool deepseek (OpenRouter) cạn dưới tải → rớt xuống gpt-4o-mini.
- Đối chiếu `ttfc_ms` (router log) vs `TTFT-answer` (client): chênh lớn ⇒ nghẽn ở proxy/graph, không ở router.

## Lưu ý an toàn

- Test tạo tải + chi phí LLM THẬT lên prod. Chạy khi được phép, tránh giờ cao điểm.
- Không ghi gì lên VM (chỉ `docker logs` / `docker exec curl /metrics`).
- User test (`loadtest01..20@company.com`) là dữ liệu thật trong user_db — xóa sau nếu cần.
