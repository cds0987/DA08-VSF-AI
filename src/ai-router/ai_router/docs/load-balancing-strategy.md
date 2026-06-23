# AI-Router — Chiến lược phân tải key qua các đợt cải tiến

> Mục tiêu: phục vụ TỐI ĐA concurrent user, **tải đều trên pool key**, đáng tin (không 429-dồn),
> trong khi query-service chỉ "đẩy request" còn ai-router lo toàn bộ chọn key/model/quota.
> Selector cắm-rút qua `routing.yaml` (`selector.impl`), KHÔNG sửa code.

## Bối cảnh: 2 LOẠI KEY có bản chất trần khác nhau

| | OpenAI key (`oai-*`) | OpenRouter key (`or-*`) |
|---|---|---|
| Trần thật | **TPM rõ** (~500K token/phút/key) | **KHÔNG cố định** — multiplex ~15 upstream |
| Tín hiệu cạn | tính trước (token/phút) | **phản ứng 429** từ upstream |
| Dùng cho | worker (gpt-5.4-mini), save-mode | plan/synth/answer/think (deepseek) |

→ Đây là lý do **không thể dùng 1 con số/1 cơ chế chung**.

## Tiến hoá selector

| Đợt | Selector | Ý tưởng | Hạn chế phát hiện |
|---|---|---|---|
| 1 | `sticky_rotation_soft` | Dính 1 key tới ngưỡng rồi tràn | Dồn tải 1 key, không tận dụng song song |
| 2 | `banded_rotation` (default) | Xoay key mỗi 250K token (band) | Tối ưu **cost/locality**, KHÔNG tối ưu concurrency → vẫn lệch |
| 3 | `weighted_banded` | Blend lane theo trọng số (node think) | Chỉ chia tỉ lệ model, không giải bài tải |
| 4 | `elastic_banded` | Slot in-flight/key + width co giãn + even-rotation theo band | **Sai TRỤC**: cap *concurrency* trong khi 1 key cho gọi đồng loạt nhiều; trần thật là *rate* |
| 5 | **`adaptive_balanced`** (hiện tại) | **Per-loại-key**: OpenAI=TPM-headroom, OpenRouter=AIMD tự dò 429 | Đúng bản chất 2 loại key (xem dưới) |

## `adaptive_balanced` — cơ chế hiện tại

```
resolve(capability) → theo tier:
  OpenAI pool   → chọn key MAX TPM-headroom; gate tpm_reserve(used+est ≤ 500K/phút)
  OpenRouter pool → chọn key MAX (limit−inflight); gate inflight < limit (AIMD)
cạn pool → save_mode (gpt-4o-mini, OpenAI) — KHÔNG 503
```

- **TPM (OpenAI)**: bucket `tpm:{key}:{minute}` (atomic Lua). Rải đều theo token/phút, 1 key nhận
  nhiều request đồng loạt tới khi chạm 500K/phút mới sang key kế. "Không ai chờ ai, trần là rate."
- **AIMD (OpenRouter)** — như TCP congestion control, **tự DÒ trần** (không cấu hình số):
  - success → `limit += 1` (additive-increase), hook ở `Router.account()`.
  - 429-rate → `limit ×= 0.5` (multiplicative-decrease) + cooldown, hook ở `Router._handle_error()`.
  - selector gate `inflight < limit`; limit hội tụ về sức thật của upstream hiện thời.
  - clamp `[2, 64]`, TTL 300s (im tải → về mặc định 8).
- State sống ở **Redis** (`tpm:`, `inflight:`, `aimd:`) → nhiều replica ai-router cùng quyết định.

Files: [counters.py] (tpm_reserve/get_tpm/get_aimd_limit/aimd_grow/aimd_shrink + in-flight),
[selector/adaptive_balanced.py], hook ở [router.py] (account=grow, _handle_error=shrink).
Test: [tests/test_adaptive_balanced.py] (OpenAI TPM spread; OpenRouter AIMD gate+grow+shrink).

## Kết quả đo (live vsfchat.cloud, prod-develop)

Load test luồng `/query` thật (Playwright bắt request → replay SSE concurrent), TTFT = token answer đầu.

| Selector | 100 concurrent | TTFT p50 | TTFT p95 | Ghi chú |
|---|---|---|---|---|
| `banded_rotation` (baseline) | 100/100 | **72s** | — | tải lệch (oai-3 ~88%, or-* 0%) |
| `elastic_banded` | 100/100 | **68.5s** | 109s | đều hơn, TTFT ~ngang |
| `adaptive_balanced` | *đang đo (25u)* | | | |

**Kết luận quan trọng (số liệu):**
- Đổi selector cải thiện **độ đều + tail (429/retry)**, **KHÔNG kéo TTFT p50 xuống** —
  vì TTFT bị chi phối bởi **latency reasoning** (deepseek nghĩ 7–19s × nhiều stage), không phải chọn key.
- Mô phỏng TTFT (sim_ttft): nút thắt p95/p99 = **tổng token deepseek/query trên pool OR**.
  Gộp worker MỘT MÌNH ≈ 0 cải thiện TTFT (worker ở pool OpenAI khác); đòn thật = **cắt token pool OR**
  (plan/verify → model nhanh off-OR + gộp synth&answer) → mô phỏng p95 −64%.

## Việc còn mở (ngoài phạm vi selector)

1. **TTFT base**: rút stage reasoning trên critical path (plan/verify nhanh, gộp synth+answer, light→answer thẳng) — đòn lớn nhất, nằm ở GRAPH (query-service), không ở ai-router.
2. **SSE jitter**: ai-router 1 event-loop (OTel ép workers=1) gánh hết stream → multi-worker/replica.
3. **Cân giữa POOL**: deepseek (OR) cạn trong khi OpenAI thừa → cho synth/answer mượn pool OpenAI khi OR cạn (thay vì save-mode sớm).
4. **Gộp worker → tool-layer thuần** (không LLM/worker): giải phóng pool OpenAI, giảm tổng call (đang tạm hoãn).

## Quan sát dashboard

Grafana `ai-router-main`: panel **Tải/Cost theo KEY** (RPM/token/cost cột) + stat **Lệch tải key**
(=(max−min)/avg RPM) để thấy `adaptive_balanced` có rải đều hơn `banded` không. Metric per-key từ
Redis (chính xác đa-worker); `airouter_key_rpm` đã khai trong `metric-contract.yaml`.
