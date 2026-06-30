# System Test Design — VSF RAG Chatbot

> Tài liệu **ý tưởng/phương pháp** đánh giá toàn hệ thống (không phải code harness — harness đã dọn,
> giữ lại tri thức). Trả lời câu hỏi: *muốn biết hệ thống chạy đúng + chịu tải đến đâu thì đo cái gì,
> đo bằng cách nào.* Kết quả số liệu thực đo: xem [benchmark.md](benchmark.md).

Hệ chạy trên **1 GCP VM** (docker-compose, prod `https://vsfchat.cloud`), SSH chỉ qua **IAP tunnel**
(cổng 22 đóng với Internet). Mọi cách test dưới đây xoay quanh ràng buộc đó.

---

## 1. Hai trục cần đo

| Trục | Câu hỏi | Cách đo |
|---|---|---|
| **Đúng (quality)** | RAG trả đúng tài liệu? Agent route đúng? ACL kín? Không bịa? | Bộ câu hỏi gắn nhãn + recall harness + RAGAS + chấm tay theo `expect` |
| **Khỏe (performance)** | TTFT/latency bao nhiêu? Chịu mấy nghìn user? Nghẽn ở đâu? | Open-loop / closed-loop load + bóc stage-latency từ Langfuse |

Hai trục **phải tách bộ dữ liệu**: đo recall trên corpus SẠCH (biết ground-truth doc), đo tải trên
corpus prod thật (đông doc, residue) — trộn vào nhau thì recall@k và latency đều nhiễu.

---

## 2. Test core code qua Playwright (UI thật, đầu cuối)

Ý tưởng: **tự lái trình duyệt** thay người, đi hết luồng người dùng + admin, bắt lỗi runtime mà unit
test không thấy (JS console, network 4xx/5xx, SSE đứt, render sai).

- **Driver**: Chromium headless qua Playwright, login thật (admin + chat), đi qua mọi route
  (`/login`, `/chat`, `/chat/[id]`, `/leave-approvals`, admin `/documents` `/users` `/audit`).
- **Bắt 3 nhóm lỗi gắn theo trang**: `pageerror` (uncaught JS), `console.error`,
  network response ≥400 (bỏ asset favicon/_nuxt/css/map/woff). Mỗi bước **chụp screenshot full-page**
  để soi regression bằng mắt.
- **Full RAG flow qua UI**: upload tài liệu trên Admin → chờ status `indexed` → sang Chat hỏi câu
  grounded trên doc vừa nạp → assert có câu trả lời + citation. Đây là e2e thật nhất (đi đúng đường
  FE → nginx → query → mcp → rag → qdrant).
- **Đơn nghỉ (action JSON)**: hỏi "xin nghỉ ..." → assert model trả PURE JSON action → form xác nhận
  hiện ra → confirm → đơn ghi vào hr-service. Kiểm cả nhánh `review_leave_approvals`.
- **Bóc stage-latency từ Langfuse qua Playwright**: login Langfuse (Basic-Auth nginx + app login),
  scrape span-tree từng trace → lấy latency theo node (plan / worker / verify·answer). Dùng để định
  lượng *nghẽn nằm ở stage nào* — thứ không nhìn ra từ TTFT tổng.

> Lưu ý vận hành: chạy với `PYTHONUTF8=1` (console Windows cp1252 vỡ tiếng Việt). Creds (admin /
> loadtest / Langfuse) **luôn qua ENV**, không hardcode.

---

## 3. Test prod qua SSH (read-only, an toàn dữ liệu)

Khi cần đo trên chính prod mà KHÔNG được làm bẩn dữ liệu:

- **Vào VM**: `gcloud compute ssh <vm> --tunnel-through-iap --command "..."` (cổng 22 đóng; cần
  `sudo docker`). Lệnh phức tạp → đóng gói base64 → `base64 -d | sudo bash`.
- **Read-only eval**: chỉ `GET /documents` + query các doc đã `indexed` sẵn; **không upload/xóa** tài
  liệu prod. Match dataset gold theo tên file, chỉ chạy nếu doc tồn tại + indexed.
- **Health preflight**: `curl -f localhost:8000..8004/health` trước khi đo; fail thì dừng sớm.
- **ACL test**: nếu prod không có sẵn doc restricted + account phân quyền → metric ACL = `not_run`
  (fail-honest, KHÔNG giả pass).
- **Smoke luồng-vàng** (đã tích hợp CD): sau deploy, mô phỏng FE gửi qua nginx — login + RAG
  (`sources>0`, outcome≠ERROR) + HR (`hr_query` outcome≠ERROR) — chọn lọc theo service vừa đổi.

---

## 4. Bộ câu hỏi gắn nhãn (labeled dataset)

Câu hỏi **grounded trên corpus thật** (Bộ luật LĐ 2019, quy chế lương VSF, sổ tay HR, doc ảnh) và
gắn nhãn để chấm tự động/bán-tự-động:

```jsonc
{ "id": "...",
  "task_type": "rag_info|hr_balance|leave_action|multiturn|ambiguous|offtopic_adv|no_doc|multiagent",
  "q": "<câu hỏi>",
  "expect": "<đáp án/hành vi đúng để chấm tay>",
  "expect_outcome": 5,           // 1 REFUSE 2 CLARIFY 3 NO_INFO 4 OFF_TOPIC 5 SUCCESS
  "group": "g1", "turn": 2,      // multiturn: cùng conversation_id
  "expect_min_workers": 2 }      // multiagent: ép fan-out ≥2 worker
```

- **single** (~150 câu): 1-lượt sạch — đo latency/correctness từng task type.
- **multiagent** (~145 câu): compound/so-sánh **ép orchestrator fan-out ≥2 worker song song** — đo
  đúng đường đa-agent (vốn chậm + dễ sai hơn).
- **multiturn**: nhiều lượt cùng `conversation_id` — kiểm memory + follow-up routing.
- **adversarial**: prompt-injection, off-topic tinh vi, câu không có trong doc (`no_doc`) → phải
  REFUSE/NO_INFO chứ không bịa.

Chấm correctness: theo trường `expect` (doc-grounded assertion); khi có `OPENAI_API_KEY` thì nối
**RAGAS** (faithfulness / answer_correctness / answer_relevancy / context precision+recall).

---

## 5. Đo tải: open-loop vs closed-loop

| Kiểu | Mục đích | Cách |
|---|---|---|
| **open-loop** (rate cố định) | Tìm điểm bão hòa của 1 nhịp thật (vd 7.5 q/s) | Bắn đúng RATE bất kể server kịp hay không → thấy hàng đợi phình |
| **closed-loop ramp** | Tìm ngưỡng chịu tải mà KHÔNG pile-up | Tăng dần concurrency, chờ response trước khi bắn tiếp |

Quy mô suy ra bằng **Little's Law**: `in-flight = QPS × latency`. Đo ở nhịp gấp ~2× tải mục tiêu để
có biên an toàn. Kết hợp **ingest đồng thời** (admin upload lúc chat đang peak) vì đó mới là giờ cao
điểm thật.

---

## 6. Recall harness (chất lượng truy hồi, tách khỏi orchestrator)

Đo recall **qua `rag-worker /api/search` raw**, KHÔNG qua `/query` — vì orchestrator có topic-gate có
thể trả 0 nguồn (giả) làm recall trông tệ oan.

- Ground-truth: mỗi câu gold gắn `document_id` đúng; recall@k = đúng doc nằm trong top-k.
- Với **multi-collection shard**: phải query MỌI collection + merge/dedup theo `chunk_id` (giữ score
  cao) — recall cũ per-collection single-model đo SAI kiến trúc shard.
- Đo cả **per-model** (recall trên shard của riêng model đó) để biết model nào đáng giữ.

---

## 7. Nguyên tắc

- **Fail-honest**: metric không đủ điều kiện đo → `not_run`, không giả pass.
- **Tách quality/perf khỏi nhau** (corpus sạch vs corpus prod).
- **Creds chỉ qua ENV**, output có thể chứa dữ liệu nhạy cảm → không commit raw data/creds.
- **Số liệu phải tái lập**: ghi rõ corpus, nhịp tải, ngày đo trong [benchmark.md](benchmark.md).
