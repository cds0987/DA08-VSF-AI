# Chiến dịch test–fix MOSA (reasoning / memory / streaming)

> Mục tiêu: test **rộng + sâu + đa dạng** để lôi edge-case THẬT, **đủ samples mới kết luận lỗi**
> (1 lần lạ = nhiễu, không phải lỗi). Mỗi route test–fix xong → ghi 1 file `.md` cặn kẽ vào
> `docs/nguyenworking/` (triệu chứng → nguyên nhân → lý do → code đã làm → từng loop) → commit-push.

## 3 trục test
1. **streaming / SSE** (QUAN TRỌNG NHẤT): không đơ (dead-air), TTFT thấp, stream liên tục.
2. **memory**: đa lượt trong 1 session (follow-up hiểu ngữ cảnh, task_state carry, working_set không tra lại).
3. **reasoning**: phân tích/so sánh/tính toán/câu mơ hồ → trả lời đúng + không đơ.

## Công cụ: `.pw-test/harness.js`
- Chạy mỗi scenario **N sample** (env `SAMPLES`, mặc định 3); mỗi sample = conversation MỚI (reset memory, tránh nhiễu chéo). Multi-turn cho memory.
- Inject hook `fetch` → bắt RAW SSE `/query`: timeline event (t, phase, node, token/text), `trace_id`, `session_id`.
- Tính/sample: `ttft_visible` (token ĐẦU user thấy), `max_gap` (đơ — khoảng dài nhất giữa 2 event visible), `total`, `answer_len`, `console_errors`.
- Aggregate/scenario: gap median + max + phân phối + no-answer count → **xác nhận lỗi nếu nhất quán đa số sample**.
- Xuất `harness_out.json` (đầy đủ raw + trace_id mỗi run).

## Đối chiếu Langfuse (không cần API key prod)
- Mỗi run bắt `trace_id` từ SSE done-event → mở trực tiếp `langfuse.vsfchat.cloud/project/rag-chatbot/traces/<trace_id>`.
- Trace ĐƠ/LỖI đã xác nhận → flag qua API `/feedback` sẵn có (score -1, token tester) → hiện **score âm** trong Langfuse → filter để xem nhanh.
- Mỗi file issue `.md` liệt kê **bảng trace_id mẫu** để bạn đối chiếu tận nơi.

## Quy trình 1 vòng
```
1. Chạy harness (đủ samples) -> agg.
2. Lỗi NHẤT QUÁN (đa số sample) = CONFIRMED; lỗi 1/N = nhiễu (giữ theo dõi, chưa fix).
3. Đào nguyên nhân: SSE timeline + Langfuse trace + đọc code.
4. Fix code.
5. Test FULL suite local + đẩy CI xanh + deploy.
6. RE-TEST harness scenario đó (đủ samples) -> xác nhận hết.
7. Viết docs/nguyenworking/<dim>-<issue>.md (format dưới) + commit-push CHUNG.
```

## Format mỗi file issue (`docs/nguyenworking/<dim>-<slug>.md`)
- **Triệu chứng**: quan sát + số liệu (gap/ttft/sample bị).
- **Cách tái hiện**: scenario + câu hỏi.
- **Nguyên nhân gốc**: cơ chế (file:line, SSE evidence).
- **Lý do nó xảy ra**: vì sao thiết kế cũ thành thế.
- **Code đã làm**: commit + diff ý chính. KHÔNG đụng cái cấm (vd JSON plan).
- **Mọi loop đã thử** (kể cả sai/false-negative): để không lặp lại.
- **Before/after** (số liệu harness + trace_id mẫu).
- **Còn lại / theo dõi**: phần chưa fix + rủi ro.

## Đã fix (link)
- (cập nhật khi có file issue)

## Bẫy đo đã dính (đừng lặp)
- Chỉ test câu DỄ → bỏ sót nhánh replan/đa lượt. PHẢI test follow-up + đa dạng.
- Sample thô (3s) → bỏ sót gap <3s. Dùng SSE event-level.
- Toggle lượt trước còn trên trang → total giả. Mỗi sample = conversation mới.
- length-flat ≠ freeze nếu có spinner. Đo theo SSE event visible, không theo độ dài text.
- Langfuse "Time to first token" = token CONTENT, KHÔNG tính reasoning đang stream → đã sửa đo ở first_tok reasoning.
