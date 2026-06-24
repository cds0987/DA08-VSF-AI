# Claude Knowledge — Load test & tối ưu "khả năng đáp ứng" AI chatbot (phiên 2026-06-24)

> Đọc file này TRƯỚC khi test tải / tối ưu lại. Đúc kết toàn bộ 1 phiên dài: cách test, benchmark,
> lỗi đã gặp, và **cách đánh giá cho ĐÚNG** (chỗ này quan trọng nhất — đừng tin nhầm số).

## 0. TL;DR — quy tắc vàng

1. **TIN SERVER-SIDE, KHÔNG tin client-side khi đo từ 1 máy.** Client httpx chạy nhiều stream trên
   1 event loop → tự nghẽn → TTFT client bị **thổi phồng** ở tải cao. Số thật = log server +
   Langfuse + ai-router `/metrics`.
2. **Máy test sau proxy công ty = số client VÔ NGHĨA.** Proxy buffer SSE → client thấy 99% im lặng
   rồi xả 1 cục (vd 31–140s ảo). Test client phải ở mạng KHÔNG qua proxy (hotspot/nhà). Xem §5.
3. **Provider (OpenRouter) tự điều phối + có credit → KHÔNG phải nút thắt.** Nút thắt là **event-loop
   của hệ** + các **van tự-bóp** (AIMD/RPM) trong ai-router.
4. **Scale service SSE = REPLICA, KHÔNG dùng `uvicorn --workers`** (workers đa-process làm "peer
   closed" cắt SSE — đã chứng minh 2/150). Replica (mỗi container 1 uvicorn) + nginx upstream.

## 1. Test gì, chạy thế nào (harness eval/load20/)

| Script | Việc | Lệnh |
|---|---|---|
| `seed_users.py` | Tạo N user test `loadtest01..N@company.com` (admin API, idempotent) | `LOAD_N_USERS=150 python seed_users.py` |
| `run_load20.py` | Bắn N user /query ĐỒNG THỜI (asyncio.Barrier), đo TTFT/dead-air/liveness + report | `LOAD_N_USERS=50 LOAD_N_BROWSERS=0 python run_load20.py` |
| `ramp.py` | Ramp nhiều mốc (TTFT-plan theo tải) | `LOAD_LEVELS=50,100,150 LOAD_N_BROWSERS=0 python ramp.py` |
| `capture_grafana.py` | Playwright chụp dashboard Grafana (chạy KHI đang tải để panel có số) | `CAPTURE_WAIT=55 python capture_grafana.py` |
| `lf_trace_timing.py` | Playwright harvest timing per-span từ Langfuse (plan/worker/answer) | `python lf_trace_timing.py` |
| `pull_vm_logs.sh` | Đọc ai-router log + đếm save_mode/429 trong cửa sổ test (read-only) | `bash pull_vm_logs.sh '<start_utc>' '<end_utc>'` |

**Env:** `LOAD_N_USERS`, `LOAD_N_BROWSERS` (số browser thật trong hybrid; 0 = toàn SSE),
`LOAD_LEVELS`, `LOAD_INSECURE=1` (bỏ SSL verify khi sau proxy — xem §5), `LOAD_BASE`,
`LOAD_USER_PW`, `LOAD_ADMIN_EMAIL/PW`. Output → `out/` (gitignored).

**Cap quan trọng:** prod đặt `QUERY_MAX_CONCURRENT_PER_USER=1000` (không chặn); nhưng nếu mặc định 3
thì 1 account KHÔNG chạy >3 concurrent → phải **N user riêng** (vì sao seed loadtest01..N).

## 2. Truy cập (cần để test/đo)

- **Prod**: `https://vsfchat.cloud` (chat), `grafana.vsfchat.cloud`, `langfuse.vsfchat.cloud`. Tất cả
  qua Cloudflare → nginx :80 → VM `35.240.193.13`. Credential admin/team đã có trong repo
  (eval/playwright-eval, eval/load20/common.py).
- **VM SSH** (đọc log/metric — port 22 egress thường bị chặn từ sandbox):
  ```
  gcloud compute start-iap-tunnel vsf-rag-demo-vm 22 --zone=asia-southeast1-a --local-host-port=localhost:2225 &
  ssh -i ~/.ssh/google_compute_engine -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2225 ttnguyen1410_gmail_com@localhost "<cmd>"
  ```
  User OS-Login = `ttnguyen1410_gmail_com` (KHÔNG phải nguyentt32). Cần `sudo docker ...`.
- **Grafana/Langfuse**: nginx basic auth `team` / `2EG4sxyGBGybDVVZ`; Langfuse login lớp 2
  `admin@company.com` / `e00015033a465bf1933b6e120b527d1f7198`. Grafana có anonymous view sau basic auth.
- **GCP**: account `ttnguyen1410@gmail.com` = **Owner** project `vintravel-chatbot` (resize VM được).

## 3. Đo SERVER-SIDE (cách đúng) — đọc gì

- **`orchestrator_preplan_timing`** (query-service log): `ctx_ms / mem_ms / save_ms / acl_ms /
  graph_ms / TOTAL_first_emit_ms` — bóc tách dead-air TRƯỚC token đầu. Đây là thứ phản ánh dead-air
  thật. Có 2 replica → gộp log `da08-vsf-query-service-1` + `da08-vsf-query-service-2-1`.
- **ai-router `/metrics`** (qua python urllib, KHÔNG có curl trong container):
  `airouter_ttfc_seconds` (time-to-first-chunk), `airouter_call_latency_seconds` (histogram →
  p95/p99), `airouter_key_inflight` (concurrency = bắt nghẽn), `airouter_key_tokens_real_today`,
  save_mode/429/no_capacity. `chat_stream_timing` log: resolve_ms/create_ms/ttfc_ms.
- **Langfuse trace**: per-span (plan/worker/verify/answer) latency + TTFT. LƯU Ý: trace chỉ bắt đầu
  từ span planner → khúc pre-plan (6–12s ở tải cao) VÔ HÌNH trong Langfuse (đã thêm span preplan.*
  + log preplan_timing để thấy).
- **Grafana dashboard** `ai-router-main`: section ① Sức khỏe (TTFT/Latency p95 màu), ② Trải nghiệm
  user (bảng + timeseries p95/p99), ④ Concurrency in-flight (nghẽn), token THẬT per key.

## 4. BENCHMARK & dòng tối ưu (đã LIVE trên prod)

**Capacity (chat /query, server-side):**
- ≤70 user: sạch, 0 degrade. 90: sạch (sau AIMD=32). **150: provider NỔI (0×429), 144–150/150**,
  degrade êm (~17 save_mode). Trần deepseek ~**150–160** = 5 OpenRouter key × AIMD_INIT(32).
- query-service 1 worker chịu 150 không restart; 2 replica chia tải → dead-air giảm.

**Dead-air pre-plan (TOTAL_first_emit, server-side — số THẬT):**
- TRƯỚC tối ưu: 50u→7.6s, 90u→8.7s, 150u→16–20s. Gốc = `load_context` summarize-LLM MỖI turn
  (5s, max 49s @150).
- SAU write-behind @15u: **0.65s**. SAU toàn bộ (gather+write-behind+defer+2replica) @30u: **~2.0s**
  (ctx 1s ∥ acl · mem 0.88s cache · save 0 defer · graph 0.93s).

**RE-BENCHMARK @150 sau commit `af8014a` (gather get_context ∥ get_allowed_doc_ids) — 2026-06-24, server-side:**
- Dead-air (TOTAL_first_emit) @150: **p50 5.78s · p95 7.98s · p99 10.84s** (n=150) — so CŨ ~10s → **−42%**.
- 150/150 served · 0×429 · **9 save_mode** (cũ ~17). ai-router ttfc avg ~5.9s. CV 0.333 (đều).
- Phân rã p50 (ms): `ctx=2520` (get_context — TO NHẤT còn lại) · `mem=2239` · `graph=2505` ·
  `save=0` (defer) · **`acl=-2229`** (ÂM = chạy SONG SONG mem → free; đúng gather opt). → đòn kế: cache/giảm get_context.
- ⚠️ Client 1-máy @150 báo dead-air 34s / TTFT-ans p50 88s = **thổi phồng ~6×** → BỎ, chỉ tin server-side.
- Cách đo: IAP tunnel (`gcloud start-iap-tunnel ... :2225`; port 22 direct timeout) → `docker logs` 2 replica
  query-service grep `orchestrator_preplan_timing TOTAL_first_emit_ms` (p-quantile) + diff `/metrics`
  `airouter_ttfc_seconds_{count,sum}`. OS-Login user = `ttnguyen1410_gmail_com`.
- ⚠️ KINH TẾ: `save_mode` degrade `gpt-4o-mini` mà gpt-4o-mini ĐẮT HƠN deepseek-flash → fallback NGƯỢC.
  9 save_mode @150 là do AIMD tự-bóp chạm trần (5key×32), KHÔNG phải provider 429 (OpenRouter có credit,
  đa-upstream hiếm hard-429). → nên: (a) nới AIMD để deepseek gánh tiếp (rẻ), hoặc (b) đổi save_mode model
  sang rẻ hơn (key deepseek khác / model rẻ), KHÔNG dùng gpt-4o-mini. "save_mode" = tránh-503, KHÔNG phải save-cost.

**Các tối ưu đã áp (tất cả live):**
1. `AIROUTER_AIMD_INIT` 16→32 (env, counters.py) — nâng trần deepseek ~150 (provider không 429).
2. `load_context` **write-behind** (client.py + redis_store.py get/set_summary) — summarize ra NỀN,
   hot-path đọc cache. Cắt 5s.
3. **defer `save_user_message`** (fire-and-forget) — bỏ 1 DB write khỏi hot-path.
4. query-service **2 REPLICA** + nginx `upstream query_pool` (docker-compose.yml, nginx.conf) —
   thay `--workers` (vốn cắt SSE). DB_POOL_MAX_SIZE cap để N×4repo×size ≤ PG max_connections.
5. PG `max_connections` 100→**200** + shared_buffers 512MB (chuẩn bị thêm replica/core).
6. **gather** `get_context` ∥ `get_allowed_doc_ids` (orchestration.py) — 2 DB read song song.
7. Dashboard: histogram TTFT/latency, inflight panel, token THẬT mọi tier (fix OR=0), bỏ nhãn
   "free_*" → provider, hết "No data" giả (`or vector(0)`).

**Còn mở (chưa làm):** scale thêm core VM (e2-custom-8/16 — owner resize được, gắn static IP TRƯỚC,
xem memory prod-dns-resize-safe); rag-worker `INGEST_WORKER_COUNT` 1→3 (ingestion tuần tự ~75s/doc);
tách key-pool chat⊥ingest (ít quan trọng vì provider không nghẽn).

## 5. LỖI ĐÃ GẶP & cách tránh (đọc kỹ!)

| Lỗi/Bẫy | Triệu chứng | Cách xử |
|---|---|---|
| **Proxy công ty buffer SSE** | client TTFT 31–140s, 99% im lặng rồi xả 1 cục; `curl` 200 nhưng python `requests` SSL CERTIFICATE_VERIFY_FAILED | Máy test ĐỔI mạng (không qua proxy). Tạm: `LOAD_INSECURE=1` để kết nối + đo SERVER-side. |
| **Client đo từ 1 máy bị thổi phồng** | client TTFT @150 = 30–36s nhưng server-side = 8–10s | Tin server-side. Client 1-máy chỉ là stress, không phải UX thật. |
| **`--workers N` (uvicorn) cắt SSE** | "peer closed connection without complete body" 148/150 | Scale bằng REPLICA (container riêng) + nginx upstream, KHÔNG `--workers`. |
| **`curl` không có trong container** | `docker exec ... curl` trả rỗng → tưởng metric vắng | Dùng `python -c "import urllib.request;..."`. |
| **CI concurrency-cancel** | build/deploy bị hủy khi người khác push develop; deploy kế SKIP service → image không rebuild | Touch 1 file trong `src/<service>/` để buộc detect rebuild + deploy. |
| **gcloud ssh 255 (deploy)** | deploy step "Deploy+healthcheck IAP SSH" fail exit 255 | Transient SSH blip — re-trigger (touch + push). Không phải code. |
| **PG config change recreate** | deploy đổi `max_connections` → postgres recreate → services reconnect → health-gate transient fail | Prod thường tự hồi (containers restart:unless-stopped + docker enabled on boot). Verify lại, re-trigger nếu cần. |
| **manifest-lint chặn metric mới** | "metric X query nhưng CHƯA khai trong metric-contract.yaml" | Khai ĐỦ tên (gồm `_bucket/_sum/_count` cho histogram) trong `deploy/monitor_decision/monitor/metric-contract.yaml`. Chạy `python deploy/monitor_decision/scripts/validate_manifest.py` cục bộ trước push. |
| **Grafana panel "No data"** | (a) refId TRÙNG trong panel → xung đột; (b) counter sự kiện chưa fire → series vắng | (a) refId duy nhất A/B/C/D; (b) `(expr) or vector(0)` để hiện 0. |
| **histogram kẹt trần bucket** | latency p95/p99 = đúng giá trị bucket cao nhất (vd 55) | Nới `LAT_BUCKETS` (observability.py) tới ~144s cho call dài. |
| **Token per-key OR = 0** | gauge token cho key OpenRouter = 0 dù deepseek chạy | Tier `paid`=limit_kind"none" không đếm token; thêm counter `obs_tok` mọi tier (đã làm). |
| **Seed bị block (agent)** | auto-classifier chặn agent ghi prod/dùng credential | Cần user cấp quyền rõ; credential là của repo, không phải đoán. |

## 6. Cách ĐÁNH GIÁ cho đúng (đừng kết luận sai)

1. **Tải nổi tới đâu** → đếm `save_mode`/`no_capacity`/`429` trong ai-router log + tỉ lệ thành công.
   "Nổi" (không sập, không degrade) ≠ "mượt" (dead-air thấp).
2. **Dead-air thật** → `orchestrator_preplan_timing TOTAL_first_emit_ms` (server). KHÔNG dùng client
   TTFT nếu đo từ 1 máy/sau proxy.
3. **Nghẽn ở đâu** → so `ttfc` router (≈1.5s) vs dead-air client/server: chênh lớn = ở GRAPH/pre-plan
   query-service, KHÔNG ở ai-router/provider. Xem `airouter_key_inflight` (đầy = nghẽn key đó).
4. **Burst đồng bộ (barrier) = worst-case**; user thật đến rải rác → nhẹ hơn. Đừng hoảng vì số burst.
5. **Token mượt khi đã chảy** (gap p95 ~0.2s) là bình thường — dead-air ĐẦU mới là vấn đề (user chờ
   trước khi thấy dấu hiệu sống). Đó là lý do ưu tiên cắt pre-plan + heartbeat.

Liên quan memory (máy này): load20-concurrency-test, prod-dns-resize-safe, observability-debug-lessons,
airouter-metrics-per-process, proxy-domain-blocks-sse, vm-ssh-access-and-db-query, gcp-access.
