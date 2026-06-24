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
cạn pool → save_mode (xiaomi/mimo-v2.5, OpenRouter — rẻ hơn gpt-4o-mini ~2.1×) — KHÔNG 503
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

## Capacity test + observability (cập nhật 2026-06-24)

**Kết quả đo tải concurrent (server-side, harness `eval/load20/`):**
- Trần deepseek ≈ **150–160 concurrent** = 5 OpenRouter key × `AIROUTER_AIMD_INIT`. Nâng INIT 16→32
  (env): provider **NỔI 150 (0×429**, AIMD không shrink), save_mode 69→17. Vượt → degrade xiaomi/mimo-v2.5 (rẻ hơn, reasoning + omnimodal).
- **Nút thắt KHÔNG ở ai-router/provider** mà ở **GRAPH query-service** (pre-plan): router `ttfc`
  p50≈1.5s nhưng client thấy event đầu 8–20s ở tải cao. Gốc dead-air = `load_context` summarize-LLM
  mỗi turn (đã write-behind → cắt 5s). ai-router `--workers` đa-process KHÔNG giúp (nghẽn ở query-service).
- **RE-BENCHMARK @150 sau commit `af8014a` (gather get_context ∥ get_allowed_doc_ids) — 2026-06-24,
  server-side**: dead-air (TOTAL_first_emit) p50 **5.78s** · p95 7.98s (CŨ ~10s → **−42%**); 150/150,
  9 save_mode, 0×429. Phân rã p50: `acl_ms` ÂM (overlap mem = gather chạy đúng), `save`=0 (defer),
  `ctx`=2.5s = đòn kế. ⚠️ Client 1-máy @150 báo dead-air 34s = thổi phồng ~6× → CHỈ tin server-side.
  Cách đo: IAP tunnel + `docker logs` 2 replica grep `orchestrator_preplan_timing` + diff `/metrics`.

**Metric mới phục vụ giám sát (observability.py + router.py):**
- `airouter_ttfc_seconds`, `airouter_call_latency_seconds` (HISTOGRAM, label capability+provider) →
  Grafana p50/p95/p99 = `histogram_quantile`, avg = rate(_sum)/rate(_count). Bucket tới 144s.
- `airouter_key_inflight` (concurrency in-flight/key — **bắt nghẽn**: gần `airouter_key_aimd_limit` = đầy),
  `airouter_key_tokens_real_today` (token THẬT mọi tier — fix 'OR=0' do tier paid limit_kind=none).
- Per-key gauge dán theo **provider** (bỏ nhãn `tier` free_* gây hiểu lầm: 1 key phục vụ cả free lẫn paid).
- Dashboard `ai-router-main` thêm section ① Sức khỏe (TTFT/Latency p95 màu), ② Trải nghiệm user
  (bảng + timeseries), ④ Concurrency in-flight. Mọi metric mới khai trong `metric-contract.yaml`
  (gate `validate_manifest.py`).

**CÁCH ĐÁNH GIÁ ĐÚNG (đọc `eval/load20/claude-knowledge/`):** tin SERVER-side (preplan log + Langfuse
+ /metrics), KHÔNG tin client-side đo từ 1 máy (thổi phồng) hay sau proxy công ty (buffer SSE → số ảo).
Scale service SSE = REPLICA (không `--workers` — cắt SSE).

## ĐO LƯỜNG ĐÚNG + RUNBOOK (interchange máy) — cập nhật 2026-06-24

> Mục này để máy khác tiếp quản đo/điều tra mà không lần mò lại. Tất cả lệnh chạy từ máy user
> (Windows git-bash), KHÔNG phải sandbox.

### Access (đọc log/metric server — port 22 KHÔNG mở ra ngoài → IAP tunnel)
```bash
# 1) tunnel (giữ chạy nền). IP VM=35.240.193.13 (STATIC reserved 'vsf-rag-vm-ip' → resize/stop KHÔNG đổi IP).
gcloud compute start-iap-tunnel vsf-rag-demo-vm 22 --zone=asia-southeast1-a --local-host-port=localhost:2225 &
# 2) ssh (OS-Login user = ttnguyen1410_gmail_com; gcloud auth = ttnguyen1410@gmail.com OWNER)
ssh -i ~/.ssh/google_compute_engine -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2225 ttnguyen1410_gmail_com@localhost "<cmd>"
```
- Container: `da08-vsf-{ai-router,query-service-1,query-service-2-1,app-postgres,qdrant,rag-worker,prometheus}-1`. Cần `sudo docker`.
- Grafana `grafana.vsfchat.cloud` (Basic Auth `team`/`2EG4sxyGBGybDVVZ`, anon view sau đó) — dashboard `ai-router-main`.
- Langfuse `langfuse.vsfchat.cloud` (Basic Auth như trên → app login `admin@company.com`/`e00015033a465bf1933b6e120b527d1f7198`).
- Prometheus KHÔNG publish ra host → query qua container có python: `docker exec query-service-1 python -c "import urllib.request;..."` tới `http://prometheus:9090`.
- Harness Node Playwright ở `.pw-test/` (KHÔNG dùng python sync_playwright — greenlet DLL fail; eval/load20 chạy được nếu `LOAD_N_BROWSERS=0`). Harness load `eval/load20/run_load20.py` (`LOAD_N_USERS=N LOAD_N_BROWSERS=0`).

### 4 TẦNG latency — metric nào đo tầng nào (ĐỪNG lẫn)
```
request ─► QUERY-SERVICE ──────────────► AI-ROUTER ──► OpenRouter(15 upstream) ─► deepseek
           [pre-plan: ctx+mem+graph]      [resolve 10ms] [create_ms = provider]
           preplan_timing TOTAL_first_emit  airouter_ttfc_seconds (≈ create_ms)
```
| Câu hỏi | Nguồn ĐÚNG | Số đo (verified 2026-06-24) |
|---|---|---|
| User thấy dấu hiệu đầu (status)? | client/FE | **~0.1s** (anti-dead-air emit ngay) |
| **User thấy TOKEN MODEL đầu (reasoning)?** | SSE phase=`thought` | **~1.1s IDLE → ~10s @150** (phụ thuộc tải) |
| User thấy token TRẢ LỜI đầu? | SSE phase=`generating` | ~26s idle (pipeline plan→worker→synth→answer) |
| Dead-air (pre-plan) server? | `orchestrator_preplan_timing TOTAL_first_emit` (query-service log) | ~1s idle → **6.4s @150** (DB contention) |
| 1 LLM-call nhanh chậm? | `airouter_ttfc_seconds` per cap (Grafana) | idle ~1s → 4s p50/13s p99 @150 |
| Tổng 1 lượt server? | Langfuse trace latency | ~33s @150 |

### TTFC decompose (chat_stream_timing log ai-router) — 4s là PROVIDER, KHÔNG phải server
`grep chat_stream_timing` → `resolve_ms/create_ms/ttfc_ms`. Verified: **resolve ~10ms (ai-router=0), ttfc≈create_ms
= OpenRouter route + deepseek first-token = 100% provider.** Phương sai lớn (create p95 6s vs median 1.3s) =
OpenRouter multiplex ~15 upstream (route nhà khác nhau). → 4s/13s là provider-under-load + variance, KHÔNG bug server.

### Histogram windowing (BẪY hay gặp)
- `airouter_*_seconds_bucket` = counter CỘNG DỒN. `histogram_quantile(.95, _bucket)` THÔ = ALL-TIME.
- Phải bọc `rate(_bucket[window])` mới theo cửa sổ. Bảng dashboard dùng `[$__range]` = theo time-picker.
- ⚠️ Load-test 150 user **nằm trong cửa sổ 3h** → vẫn nhiễm. Xem sạch: picker **15-30m** (loại test cũ) HOẶC chờ test trôi ra >3h.
- Tail "2.40 min" = trần bucket 144s (đụng khi stress/timeout); @15m sạch tail ~50s.

### CLIENT-1-máy ở tải cao = SỐ ẢO (đã chứng minh bằng mâu thuẫn vật lý)
@150: client TTFT-answer **70s** > Langfuse total-turn server **33.5s** → token đầu KHÔNG THỂ tới sau khi
turn đã xong → client đọc 125 SSE không kịp → thổi **~2-4×**. → tải cao CHỈ tin server-side. Client chỉ
đúng ở **concurrency thấp** (sequential/≤5).

### Quick-wins đã làm (2026-06-24, $0 hardware)
1. **rag-worker NAK-storm** (`s3_artifact_store.delete_by_document` nuốt NoSuchKey + `ingest_consumer` nak(delay=5)):
   doc.access(deleted)→delete NoSuchKey→nak-loop 35/s đốt **110% CPU idle** → fix → **1.14% CPU** (free ~1 core).
2. **get_context 1 round-trip** (LATERAL, `postgres_conversation_repo`): giảm pool contention trong dead-air.
3. **anti-dead-air** (`orchestration` emit status t≈0 + `Pipeline.vue` rotating hint): first-visible 112ms.

### VM resize an toàn (cores+RAM, 1 VM)
IP static → resize KHÔNG đổi IP → mọi expose (vsfchat/grafana/langfuse/qdrant qua Cloudflare→static IP)
SỐNG. `stop → set-machine-type=e2-custom-N-MEM → start`. Disk persistent không đụng (data PG/Qdrant giữ).
Để app DÙNG core mới = thêm REPLICA (1 worker=1 core; --workers cắt SSE) → kèm fix **SSE/notification fanout
in-memory** (ConnectionManager) kẻo notification rớt xuyên replica. Dead-air @4core CHƯA chạm trần CPU
(load 0.92/4, query-service 3% CPU; dead-air = DB/model latency, nâng core KHÔNG giảm dead-air).

### //hóa MODEL (chia tải nhiều model 1 capability) — cơ chế + thử nghiệm 2026-06-24
**Vì sao**: p99 ttfc 12s @150 = **QUEUE inference UPSTREAM** (GPU provider), KHÔNG phải credential/key
(ai-router 10ms, ttfc≈create_ms=provider). Chia tải 2 model = 2 upstream GPU khác nhau → mỗi cái nửa tải
→ queue nông → p99 thấp. **Chỉ thắng nếu 2 model NHANH NGANG nhau.**
**Cơ chế (GIỮ, dùng lại được)**: `adaptive_balanced._pick_model_split` — `models[tier]` là LIST → ROUND-ROBIN
(`next_seq`) thay failover-first; vẫn AIMD key-balance (cùng pool OR key). Bật = routing.yaml `models.paid: [m1, m2]`.
**Thử deepseek+xiaomi 50/50 → REVERT** (đo thật):
- deepseek ttfc p99 **12.99→8.78s** (split ĐÚNG cơ chế, nửa tải giảm tail ✓).
- **NHƯNG xiaomi/mimo-v2.5 ttfc p99 = 15.21s** (upstream chậm/variance hơn) → p99 TỔNG ≈15s **XẤU hơn** deepseek-only; success 125→84/150 (xiaomi sinh chậm → hold lâu → timeout).
- → p99 = 1% chậm nhất; ≥1% đi model chậm thì p99 tổng vẫn cao. **//hóa cần model thứ 2 nhanh ngang deepseek** (vd deepseek-pro KHÔNG nhanh; cần đo 1 OR model ttfc thấp trước khi //hóa). xiaomi giữ role **save_mode** (overflow rẻ), KHÔNG làm primary.
