# Kế hoạch Observability tập trung & AI Operations — DA08-VSF-AI

> Tài liệu xương sống. Trạng thái: **đề xuất, chờ duyệt**. Chưa đụng code production.
> Phương pháp: **task-centric, top-down** — (1) liệt kê task hệ thống → (2) định nghĩa hợp đồng đo
> cho từng task → (3) câu hỏi vận hành per task → (4) dashboard. Hạ tầng (OTel/Tempo/Loki) chỉ là
> phương tiện hiện thực, đặt sau cùng. Mục tiêu: trả lời 7 câu hỏi AI Ops, đo **toàn bộ chi phí +
> hiệu năng** mọi task, và để **sẵn nền** control plane auto-balance + human-in-the-loop.

---

## Phương pháp 4 bước (xương sống tài liệu)

1. **Hệ thống cần làm gì** → Task Inventory + Dependency Map (§1).
2. **Mỗi task đánh giá & trace thế nào** → Task Contract: input/output/success/failure/SLO/cost/deps/retry-fallback/trace (§2–§3).
3. **DevOps/SRE cần trả lời câu hỏi gì** per task (§4).
4. **Mới thiết kế dashboard** (§5). Hạ tầng hiện thực (§6), control plane (§7).

---

## §1. Task Inventory + Dependency Map (Bước 1)

### 1.1 Bản đồ luồng (một request user xuyên hệ)

```
USER ──▶ nginx ──▶ user-service(auth) ──▶ query-service ──┬──▶ ai-router ──▶ OpenAI/OpenRouter (LLM)
                                                           ├──▶ mcp-service ──▶ embed ──▶ Qdrant ──▶ rerank
                                                           └──▶ hr-service
INGEST (nền): document-service ──▶ NATS ──▶ rag-worker ──▶ parse/OCR ──▶ chunk ──▶ caption ──▶ embed ──▶ Qdrant
                                                                          (caption/embed đi qua ai-router)
HẠ TẦNG: postgres×5 · redis · nats · qdrant · GCS (artifact + tài liệu)
```

### 1.2 Danh sách task + độ phủ observability hiện tại

🟢 đủ · 🟡 một phần · 🔴 mù. (Cột "Trace/Cost/Latency" = đang có gì; dẫn chứng §8 phụ lục.)

| Domain | Task | Phụ thuộc | Retry/Fallback/Timeout | Trace | Cost | Latency |
|---|---|---|---|:--:|:--:|:--:|
| **Gateway** | `gateway.request` (nginx route) | backend service | timeout 30s (3600s SSE), **no rate-limit ở nginx** | 🔴 | — | 🔴 |
| **Auth** | `auth.login` | user-service, postgres | lockout 5 fail/15ph | 🟡 NR | — | 🔴 |
| | `auth.verify_token` (JWT) | user-service | timeout 5s, fail→401 | 🔴 | — | 🔴 |
| | `auth.acl_allowed_docs` | doc-access repo, cache | timeout 10s, cache 1s→DB | 🔴 | — | 🔴 |
| **Query** | `query.guardrail` (LLM-judge injection) | ai-router(LLM) | **fail-OPEN** (lỗi→không chặn) | 🟡 | 🔴 | 🟡 |
| | `query.triage` (phân loại) | ai-router(LLM) | parse fail→"allow" | 🟢 | 🟢 | 🟢 |
| | `query.think` (quyết định tool) | ai-router(LLM) | timeout 30s | 🟢 | 🟢 | 🟢 |
| | `query.semantic_cache` | redis | timeout 1s, fail-OPEN | 🔴 | — | 🔴 |
| **Retrieval** | `retrieval.embed_query` | mcp→ai-router | timeout 5s | 🔴 | 🔴 | 🔴 |
| | `retrieval.vector_search` (Qdrant) | qdrant | timeout 10s, hybrid RRF | 🔴 | — | 🔴 |
| | `retrieval.rerank` | lexical/LLM | timeout 30s, fallback→noop | 🔴 | 🔴 | 🔴 |
| | `retrieval.rag_search` (tổng, qua MCP) | mcp-service | timeout 15s, **circuit breaker 5 fail/30s**, fail-OPEN | 🟡 (tool span tổng) | 🔴 | 🟡 |
| **LLM** | `llm.generate` (answer stream) | ai-router | timeout 30s, retry 0 | 🟢 | 🟢 | 🟢 |
| **Output** | `output.guardrail_redact` (PII) | regex | fail-OPEN | 🔴 | — | 🔴 |
| | `output.validate` (outcome/fallback detect) | regex | — | 🔴 | — | 🔴 |
| **Routing** | `airouter.resolve` (chọn key/tier/model) | registry, counters | 4 attempts, tier cascade, cooldown 30s | 🟡 metric | — | 🔴 |
| | `airouter.reserve` (quota Lua atomic) | redis | fail→key kế | 🔴 | — | 🔴 |
| | `airouter.call_provider` | OpenAI/OpenRouter | 4 attempts, model cooldown 30s | 🟡 log | 🟢 | 🔴 |
| | `airouter.account` (usage/cost) | redis, catalog | best-effort | 🟢 metric | 🟢 | — |
| **Ingest** | `ingest.parse` (parse/OCR, GCS) | GCS, parser | timeout 600s job, retry S3 | 🟢 span | 🔴 (GCS) | 🟢 |
| | `ingest.chunk` | chunker | limit 50k, no retry | 🟢 | — | 🟢 |
| | `ingest.caption` (vision LLM) | ai-router | retry 5+backoff, fallback snippet, threshold 0.3 | 🟢 span | 🟡 thiếu token | 🟢 |
| | `ingest.embed` | ai-router | batch 100, retry 5+backoff | 🟢 span | 🔴 thiếu token | 🟢 |
| | `ingest.qdrant_write` | qdrant | no retry riêng | 🟢 span | — | 🟢 |
| **Infra** | postgres×5 / redis / nats / qdrant | — | healthcheck một phần | 🔴 | 🔴 | 🔴 |
| | VM compute (e2-standard-4) | GCP | — | 🔴 | 🔴 | 🔴 |
| | GCS storage + egress | GCP | — | 🔴 | 🔴 | — |

**Đọc bảng:** chỉ luồng **LLM chat** (triage/think/answer) là 🟢 cả 3 chiều. **Retrieval (embed/search/rerank), gateway, auth, output, infra, GCS** gần như mù — đây đúng là nơi hay chậm/tốn mà không thấy.

---

## §2. Task Contract — template chuẩn (Bước 2)

Mỗi task mô tả bằng hợp đồng sau. Đây là artifact cốt lõi — dashboard (§5) suy ra từ đây.

```yaml
task: <domain.name>
owner: <service/team>              # gắn docs/team-ownership.md
depends_on: [<task/service>]
input:  <gì>
output: <gì>
success: <định nghĩa SLI>
failure: <định nghĩa + các failure mode>
slo:                               # ngưỡng: default ship sẵn → devops chỉnh tay (Config Store) → track history
  latency_p99: <ms>
  error_rate:  <%>
  quality:     <ngưỡng, nếu task AI>
cost:
  type: pay-per-use | infra | none
  fields: [tokens, cost.usd]       # map canonical schema §3
retry_fallback: <cơ chế thật>
observability:
  trace_span: <tên span>
  metrics: [<RED + cost>]
  sample_rate / retention: <...>
alerts:                            # cầu nối câu hỏi "làm gì ngay"
  - condition: <vượt SLO>
    severity: P1|P2|P3
    runbook: <link>
devops_questions: [ ... ]          # §4
```

---

## §3. Task Contract — điền sẵn các task xương sống (mẫu)

> Điền đầy đủ 6 task có rủi ro/độ mù cao nhất. Các task còn lại điền theo cùng khuôn ở giai đoạn thực thi.

### 3.1 `gateway.request` (nginx) — 🔴 hiện mù
```yaml
owner: devops / nginx
depends_on: [user/document/query/mcp/hr-service]
input:  HTTP request (path, method, headers, client IP)
output: HTTP response (status, bytes, duration)
success: 2xx/3xx
failure: 4xx (client) / 5xx (backend) / upstream timeout (30s, 3600s SSE)
slo: { latency_p99: TBD-baseline, error_rate: <1% 5xx }
cost: { type: infra }
retry_fallback: KHÔNG (nginx không rate-limit; rate-limit ở app layer)
observability:
  trace_span: gateway.request (sinh trace_id GỐC, truyền traceparent xuống)
  metrics: [requests_total{route,status}, request_duration, upstream_latency]
alerts:
  - { condition: 5xx rate > 1% 5m, severity: P1, runbook: runbook/gateway-5xx }
devops_questions: [bao nhiêu req vào, req nào bị từ chối, backend nào chậm, traffic user nào tăng bất thường]
```

### 3.2 `auth.verify_token` — 🔴 hiện mù
```yaml
owner: user-service
depends_on: [user-service, postgres]
input:  Bearer JWT
output: User{id, role, department} | 401
success: token hợp lệ, chưa hết hạn
failure: JWTError/expired/missing claim → 401 ; user-service timeout 5s → 401 (fail-closed)
slo: { latency_p99: 50ms, error_rate: <2% 401-do-lỗi-hệ-thống }
cost: { type: infra }
retry_fallback: KHÔNG retry; timeout→401
observability:
  trace_span: auth.verify_token
  metrics: [auth_attempts_total{result}, auth_latency, lockouts_total]
alerts:
  - { condition: 401-system-error spike, severity: P2, runbook: runbook/auth }
devops_questions: [auth có lỗi không, bao nhiêu 401/403, account bị khóa nhiều không]
```

### 3.3 `airouter.resolve` + `airouter.call_provider` — 🟡 metric có, trace/latency thiếu
```yaml
owner: ai-router / devops
depends_on: [registry, counters(redis), OpenAI, OpenRouter]
input:  capability(embed/chat), est_tokens, has_tools, has_image
output: RouteDecision{key_id, provider, tier, model} | None(no_capacity)
success: chọn được key sống + reserve quota OK + provider 200
failure: unknown_capability | no_capacity(mọi tier cạn) | provider 4xx/5xx/429
slo: { latency_p99: 200ms-overhead, error_rate: <1%, fallback_rate: <10% }
cost: { type: pay-per-use, fields: [tokens.input, tokens.output, cost.usd, key_id, tier] }
retry_fallback: 4 attempts; tier cascade free_oai→free_or→paid; key 429→cooldown 30s; model lỗi→cooldown 30s
observability:
  trace_span: airouter.resolve, airouter.call_provider (gắn key_id/provider/tier/cost vào span)
  metrics: [resolve_total, fallback_total, resolve_fail_total{reason}, key_tokens_today, key_cost_month_usd, key_cooldown]  # ĐÃ CÓ
  THIẾU: latency per provider/model, error per key
alerts:
  - { condition: fallback_rate > 10% 5m, severity: P2, runbook: runbook/airouter-fallback }
  - { condition: resolve_fail{reason=no_capacity} > 0, severity: P1, runbook: runbook/keys-exhausted }
  - { condition: key_remaining < 10% quota, severity: P2, runbook: runbook/quota-burndown }
devops_questions: [request route vào key nào, key nào healthy/429/sắp hết credit, model nào dùng, fallback vì sao, nếu key chết còn đủ capacity không]
```

### 3.4 `retrieval.vector_search` (Qdrant) — 🔴 hiện mù hoàn toàn
```yaml
owner: mcp-service / devops
depends_on: [qdrant]
input:  query vector (1024-dim), top_k, doc_filter(ACL)
output: List[SearchHit]{score, doc_id, chunk}
success: trả ≥1 hit ; (chất lượng: top score ≥ threshold)
failure: 0 hit | Qdrant timeout 10s | collection missing/dim mismatch
slo: { latency_p99: 200ms, error_rate: <0.5%, quality: top_score ≥ threshold }
cost: { type: infra }
retry_fallback: KHÔNG retry; hybrid(dense+sparse RRF) hoặc dense theo collection
observability:
  trace_span: retrieval.vector_search (THÊM MỚI)
  metrics: [search_latency, hits_count, top_score, empty_result_total, collection]
alerts:
  - { condition: empty_result_rate > X% | p99 > 200ms, severity: P2, runbook: runbook/qdrant }
devops_questions: [Qdrant có phản hồi không, latency bao nhiêu, có lấy được tài liệu không, score quá thấp không, collection nào có vấn đề, embedding model có đổi không]
```

### 3.5 `llm.generate` (answer) — 🟢 tốt, bổ sung chất lượng
```yaml
owner: query-service
depends_on: [ai-router]
input:  question + context(RAG/HR) + history
output: answer (stream tokens) + usage
success: có token, format hợp lệ, KHÔNG fallback message
failure: exception→answer="" | output rỗng→NO_INFO | invalid schema
slo: { latency_p99: TBD, cost_per_req: TBD, quality: groundedness ≥ X }
cost: { type: pay-per-use, fields: [tokens.input, tokens.output, cached_tokens, cost.usd] }  # ĐÃ CÓ
retry_fallback: timeout 30s, retry 0; lỗi→fallback message tĩnh
observability:
  trace_span: llm.generate (generation: model, usage, cost — ĐÃ CÓ)
  THÊM: quality score (groundedness/judge sample), output validity
alerts:
  - { condition: cost_per_req tăng >X% | invalid_output_rate > Y%, severity: P2 }
devops_questions: [provider nào chậm, model nào lỗi nhiều, cost/req tăng không, token input tăng vì prompt nào, output hợp lệ không, chất lượng giảm không, retry/fallback tốn thêm bao nhiêu]
```

### 3.6 `ingest.embed` + `ingest.caption` — 🟡 span có, COST thiếu token
```yaml
owner: rag-worker
depends_on: [ai-router, qdrant]
input:  chunks/sections text (batch 100)
output: vectors[dim] / captions
success: #vector = #input, đúng dimension ; caption fallback_rate < 0.3
failure: dim mismatch | TransientAIError | CaptionFallbackThresholdExceeded
slo: { latency_p99: TBD, cost_per_doc: TBD, fallback_rate: <30% }
cost: { type: pay-per-use, fields: [embedding.tokens, cost.usd] }  # ⚠️ HIỆN KHÔNG ghi token
retry_fallback: retry 5 + exponential backoff + jitter; caption→snippet[:600]
observability:
  trace_span: ingest.embed, ingest.caption (ĐÃ CÓ span)
  ⚠️ FIX: lấy usage từ provider hoặc tính catalog → ghi token+cost vào generation
  metrics: [caption_calls_total, caption_fallback_rate (ĐÃ CÓ); embed_tokens, embed_cost (THÊM)]
devops_questions: [cost ingest/doc bao nhiêu, embedding model đổi không, caption fallback nhiều không]
```

---

## §4. Câu hỏi vận hành per task (Bước 3)

Gom theo domain — đây là tiêu chí để dashboard "có ích" chứ không chỉ "đẹp".

- **Gateway:** Bao nhiêu request đang vào? Req nào bị từ chối? Auth lỗi không? Rate-limit có chạm? Backend nào chậm? Traffic user/project nào tăng bất thường?
- **Routing & API key:** Request route vào key nào? Key nào healthy? Key nào 429? Key nào gần hết credit? Model nào đang dùng? Fallback có xảy ra? Vì sao fallback? Nếu key này chết, còn đủ capacity không?
- **Retrieval:** Qdrant có phản hồi? Latency bao nhiêu? Có lấy được tài liệu? Score quá thấp không? Collection nào có vấn đề? Embedding model có đổi?
- **LLM generation:** Provider nào chậm? Model nào lỗi nhiều? Cost/request tăng không? Token input tăng vì prompt nào? Output hợp lệ? Chất lượng giảm không? Retry/fallback tạo chi phí phụ không?
- **Output validation:** Bao nhiêu response sai JSON schema? Field nào thường thiếu? Model nào tạo invalid output nhiều? Prompt version nào gây lỗi? Có trả response lỗi cho user không?
- **Ingest:** Job pending/processing/failed bao nhiêu? Caption fallback rate? Cost/doc? Queue depth & sweep lag?
- **Infra/Cost tổng:** CPU/RAM/đĩa mỗi service? Qdrant/Postgres latency? GCS egress + storage tốn bao nhiêu? Tổng cost thật/request (LLM + embed + infra)?

---

## §5. Dashboard trung tâm 7 câu hỏi (Bước 4)

Suy ra từ §1–§4. Một cửa Grafana, nhúng admin FE `/admin/ops/*` (gate role `devops`).

| Vùng | Trả lời câu | Nguồn |
|---|---|---|
| Health bar mọi task (RED: rate/error/latency) | 1. Có chuyện gì? | metrics per-task |
| Service/Task map sáng-đỏ | 2. Ở đâu? | Tempo + metrics |
| Impact: %user lỗi, #request, theo role/department | 3. Ai & bao nhiêu? | metrics + trace attrs |
| Click task lỗi → trace → log cùng `trace_id` | 4. Vì sao? | Tempo + Loki |
| **Cost tổng:** LLM + embed + caption + infra + GCS theo key/tier/model | 5. Tốn bao nhiêu? | airouter metrics + catalog + GCP billing |
| Quality: feedback score, groundedness, fallback_rate, invalid_output | 6. AI còn đúng? | Langfuse score + judge |
| Alert feed + runbook + (control plane) đề xuất | 7. Làm gì ngay? | Alertmanager |

---

## §5b. Kịch bản: chẩn đoán khi user than "trả lời sai / tài liệu không chính xác"

> Sự cố KHÓ NHẤT: mọi đèn xanh (không 5xx/timeout/exception) nhưng **câu trả lời sai**.
> Infra observability vô dụng ở đây — cần tín hiệu CHẤT LƯỢNG + trace từng tầng.

### Một câu trả lời tồi có thể gãy ở 5 tầng (cách sửa mỗi tầng khác nhau)
| # | Gãy ở đâu | Triệu chứng | Task | Cách sửa |
|---|---|---|---|---|
| 1 | Retrieval sai (lấy nhầm/không lấy được doc) | top_score thấp, hits ít, ACL lọc mất | `retrieval.vector_search` | tune ngưỡng/embedding |
| 2 | Rerank loại nhầm doc đúng | doc đúng có trong search, mất sau rerank | `retrieval.rerank` | tune rerank |
| 3 | Doc không có trong index (lỗi ingest) | caption fallback, chunk hỏng, embed sai | `ingest.*` | **re-ingest** |
| 4 | LLM bịa (context đúng nhưng phớt lờ) | answer không khớp source | `llm.generate` | sửa prompt/model |
| 5 | Doc cũ/sai trong index | index giữ bản lỗi thời | `ingest` + version | cập nhật nguồn |

### Chuỗi chẩn đoán 4 bước
1. **Bắt lời than, gắn đúng trace.** User 👎 → ghi **score âm vào Langfuse theo `trace_id`/`session_id`**. (Hiện CHƯA hiển thị trên dashboard — thêm Phase 5.)
2. **Mở trace, đọc từng tầng để khoanh vùng** (cần retrieval hết mù — Phase 2):
   ```
   trace abc123 (👎)
   ├─ retrieval.vector_search → hits=2, top_score=0.41  ⚠️ thấp → nghi tầng 1/3
   ├─ retrieval.rerank        → giữ 2 doc
   ├─ llm.generate            → answer vs context
   └─ groundedness=0.9        → answer KHỚP context ⇒ lỗi ở RETRIEVAL, không phải LLM
   ```
   Quy tắc khoanh vùng: top_score cao + groundedness thấp → **LLM bịa**; top_score thấp → **retrieval/ingest**.
3. **2 điểm chất lượng phải thêm (Phase 5):** `retrieval.relevance` (doc lấy về có liên quan?) và `groundedness/faithfulness` (answer có bám doc?). Hai số này tách bạch "lỗi tìm kiếm" vs "lỗi sinh".
4. **Một lần hay hệ thống?** Gom feedback âm theo collection/model/prompt_version/thời gian:
   - một collection bị dồn 👎 → re-ingest (tầng 3)
   - một prompt_version sau khi đổi → rollback (tầng 4)
   - top_score thấp rải rác → ngưỡng/embedding model có vấn đề

### Giới hạn kỳ vọng
Observability KHÔNG tự biết đúng/sai sự thật. Nó: bắt *tín hiệu* bất mãn → **khoanh tầng gãy trong vài phút** → phát hiện *xu hướng* để sửa gốc. Phán xét đúng/sai cuối cùng cần **golden dataset + eval định kỳ** (`docs/golden-dataset-criteria.md`, `eval/`) — final version nối hai cái này vào dashboard chất lượng.

---

## §6. Hạ tầng hiện thực — lộ trình phase (phương tiện, đặt sau)

Mỗi phase tự có giá trị, rollback được, **app không bao giờ phụ thuộc observability**.

- **Phase 0 — Canonical schema (§3 fields):** chốt từ điển chung (OTel semantic conventions) gồm cả field future strategy: `user.id/role/department`, `request.id`(=trace_id), `llm.model/provider/key_id/tier/tokens`, `cost.usd/type`, `embedding.model/tokens`, `retrieval.hits/latency/top_score`, `rerank.model`, `task.name/duration_ms/status`. Giấy bút, RAM 0.
- **Phase 1 — OTel Collector + Alertmanager:** Collector (nơi chuẩn hóa tập trung) + alert đầu tiên cho AI Router (đã có metric): fallback spike, quota burndown, key cooldown, no_capacity. Quick win, không đụng app.
- **Phase 2 — OTel hóa TOÀN BỘ service (3 đợt), bọc span MỌI task §1:**
  - 2a. Xương sống: `gateway → auth → query → airouter → mcp(embed/search/rerank) → llm`. Sinh `trace_id` tại nginx, truyền `traceparent` suốt. **Bọc span các task hiện mù: vector_search, embed_query, rerank, output.validate.**
  - 2b. Vệ tinh: user/document/hr-service, rag-worker (nâng đầy đủ + ghi token embed/caption).
  - 2c. Frontend chat+admin: trace + error, nhận `trace_id` từ backend.
  - 2d. **mcp-service phải có tracer** (hiện hoàn toàn chưa có).
- **Phase 3 — Backend lưu trữ: Tempo + Loki** (VM 16GB đủ dư địa). Thêm **node-exporter + cAdvisor + postgres/redis/qdrant exporter** + kéo **GCP billing/Monitoring** (GCS egress + VM) → lấp cost hạ tầng. Dữ liệu cũ: traces/logs cut-over; cost/usage backfill.
- **Phase 4 — Dashboard §5 + RED per-service + dọn New Relic & LangSmith** (giữ Langfuse cho UI LLM sâu).
- **Phase 5 — Quality (câu 6) + nền control plane (§7):** thêm 2 điểm chất lượng (`retrieval.relevance`, `groundedness`) + feedback lên dashboard (§5b). Dựng **Config/Policy Store trung tâm** + cho mọi service đọc model/threshold động (nền Công tắc B) + Công tắc A (sampling runtime) + Human gate 3 nấc. Chưa cần thuật toán/agent thật — chỉ "ổ cắm" sẵn để ráp AI-reasoning sau.

---

## §7. Control Plane — 2 công tắc toàn hệ + auto-balance + human-in-the-loop

> Áp dụng SAU, nhưng **compatible từ đầu — không đập đi xây lại.** Mô hình MAPE-K.

### 7.0 HAI CÔNG TẮC TOÀN HỆ (yêu cầu cốt lõi)

Final version có **2 công tắc trung tâm**, đối xứng nhau: một để NHÌN, một để CAN THIỆP — đều tác động **toàn hệ, tức thì runtime, không restart**.

```
        ┌─────────────── CONTROL PLANE (1 cửa /admin/ops/*) ───────────────┐
        │                                                                   │
        │   CÔNG TẮC A — OBSERVE          CÔNG TẮC B — INTERVENE            │
        │   (trace toàn hệ)              (can thiệp toàn hệ)                │
        │   • bật/tắt trace toàn bộ      • đổi embedding model             │
        │   • chỉnh sample rate         • đổi generate model              │
        │   • debug-mode 100% spans     • đổi ngưỡng retrieval/rerank     │
        │   • verbosity per task        • đổi strategy balance / weight   │
        │          │                            │                          │
        │          ▼                            ▼                          │
        │   Observability Config        Config/Policy Store               │
        │          │                    [HUMAN GATE 3 nấc + guardrail + audit]
        └──────────┼────────────────────────────┼──────────────────────────┘
                   ▼                             ▼ mọi service ĐỌC RUNTIME (watch/reload)
            OTel Collector              nginx · query · mcp · rag-worker · ai-router
            (đổi sampling)              (đọc model/threshold động, KHÔNG từ env tĩnh)
```

**Công tắc A — Trace toàn hệ (observe):**
- Một chỗ bật/tắt + chỉnh độ chi tiết trace cho TOÀN BỘ task, runtime. Bình thường sample thấp (tiết kiệm); khi điều tra → bật "debug-mode" 100% spans cho 1 user/route/khoảng thời gian.
- Hiện thực: Collector + OTel SDK đọc cấu hình sampling động (head/tail sampling). Không sửa code service.

**Công tắc B — Can thiệp toàn hệ (intervene):**
- Một chỗ đổi **embedding model / generate model / ngưỡng / strategy** áp ngay toàn hệ, runtime.
- **Điều kiện compatible (nền PHẢI làm sẵn bây giờ):** hiện model nạp từ **env lúc boot** (`EMBED_MODEL`, `LLM_MODEL`, capability map) → muốn đổi phải restart. Để đổi tức thì, mọi service phải **đọc các field này từ Config/Policy Store trung tâm** (watch/hot-reload), KHÔNG từ env tĩnh. AI Router đã có `/admin/reload` → mở rộng pattern ra **mọi service**.
- Đi qua **đúng 1 cổng "apply"** = Human gate 3 nấc + guardrail + audit (giống auto-balance).

**Nền cho AI-reasoning fix tại runtime (ráp sau):**
- Vì cả 2 công tắc đều đi qua Config/Policy Store + cổng "apply" chuẩn → sau này một **LLM reasoning agent** chỉ cần: đọc observability (qua công tắc A) → suy luận → **đề xuất một config change** (qua công tắc B) → vào human gate. Agent KHÔNG cần quyền đặc biệt, KHÔNG sửa kiến trúc — nó chỉ là "một tác nhân nữa đề xuất policy". Đây là điểm cắm AIOps.
- Bất biến an toàn: AI đề xuất ở nấc Advisory/Approval trước; chỉ lên Autonomous khi đủ tin cậy; guardrail (vd không đổi sang model chưa whitelist, không vượt trần cost) + audit luôn chặn.

### 7.0b Access control 2 tầng (MVP — giữ đơn giản)
- **Tầng Xem (Observe):** login thường (dev/staff) → dashboard read-only, xem trace/metric/log + Công tắc A (độ chi tiết trace). JWT bình thường.
- **Tầng Tune (Control):** **1 top-secret account duy nhất, đúng 1 người**, token **dài hạn**, account tách biệt bên ngoài; dev thường KHÔNG chạm. Đây là cổng duy nhất dùng Công tắc B + apply policy.
- Bảo mật cao chỉ gom ở **1 cổng apply** (defense-in-depth, audit). Service khác chỉ ĐỌC config (read-only). Hoãn sau MVP: dual-control, secret per-người, token ngắn hạn, xoay vòng.
- **Ưu tiên MVP: dashboard "nhìn" (Phase 0→4) trước; "can thiệp" (Phase 5) sau** — chỉ cần nền Config Store đọc động sẵn.

### 7.1 MAPE-K — auto-balance (xây trên cùng nền 2 công tắc)

```
Knowledge = observability đã gom (§1–§6)
Monitor → Analyze → Plan(Strategy plugin) → [HUMAN GATE] → Execute(AI Router)
```
- **Tách 2 mặt phẳng:** AI Router = *data plane*, CHỈ thực thi, đọc policy runtime (mở rộng `/admin/reload`). Thuật toán balance ở *control plane* riêng.
- **2 ổ cắm bắt buộc có sẵn:**
  - **Policy Store** + AI Router đọc policy động (`{strategy, weights{key_id}, caps{tier}, overrides}`).
  - **Strategy interface** `decide(observability_snapshot) → proposed_policy`. Chiến lược sau: round-robin, weighted, cost-optimal, latency-aware, quota-burndown-aware, quality-aware, ML/predictive.
- **Human-in-the-loop — công tắc 3 nấc:** Advisory (chỉ đề xuất) → Approval (chờ duyệt trên `/admin/ops/*`) → Autonomous (tự áp, trừ khi vượt guardrail). **Guardrail + audit log luôn bật mọi nấc.**
- **1 cổng "apply policy" duy nhất** → đổi mức tự động hóa = đổi config, không sửa kiến trúc.
- **Phụ thuộc observability:** strategy `latency-aware` cần latency per provider, `cost-optimal` cần cost đầy đủ (gồm embed/infra) → chính là lý do Phase 0–3 phải đo đủ. Quan sát thiếu thì điều khiển mù.

---

## §8. Tổng kết lỗ hổng (ưu tiên giảm dần)

1. **Không có alert nào** — Prometheus chỉ thu, không báo. Lấp ở Phase 1.
2. **trace_id xuyên service = 0%** — không nối được request giữa các tool. Lấp Phase 2.
3. **Retrieval mù hoàn toàn** (embed_query, vector_search, rerank không span/latency/cost) — phần hay chậm nhất. Lấp Phase 2.
4. **mcp-service không có tracer** — hộp đen giữa luồng query.
5. **Cost mới đo phần token LLM** — embed thiếu token, infra/GCS/VM mù → câu 5 chỉ đúng một phần.
6. **Frontend mù** — không trace, không error tracking.
7. **Chất lượng AI chỉ suy đoán qua fallback** — chưa có groundedness/feedback. Lấp Phase 5.
8. **Hạ tầng thiếu exporter** (node/cAdvisor/postgres/redis/qdrant) + thiếu healthcheck nhiều service.

---

## §9. Bản đồ phase ↔ câu hỏi & ràng buộc

| Phase | Lấp câu | Ràng buộc |
|---|---|---|
| 1 | 1, 7 (AI Router) | VM **16GB** (e2-standard-4, ~13Gi free) — đủ Tempo/Loki; vẫn check `docker stats`. |
| 2 | 2, 4 | App KHÔNG phụ thuộc observability (best-effort). |
| 3 | 2, 4, 5 (toàn hệ) | OTel hóa tăng dần từng service; test latency không tăng. |
| 4 | 1, 2, 3, 5, 7 | Đừng nhúng AI/auto-balance trước khi gom+chuẩn hóa xong. |
| 5 | 6 + nền control plane | |

## §10. Khởi động đề xuất
**Phase 0 (canonical schema, điền nốt Task Contract còn lại) + Phase 1 (Collector + Alertmanager)** — rẻ nhất, không đụng app, cho cảnh báo thật ngay, đặt nền cho mọi phase sau.

---

## §11. Cập nhật từ phiên thảo luận (2026-06-17) — đính chính + cụ thể hoá

> Bổ sung cho §1, §7, §8. KHÔNG thay nội dung cũ; chỉ sửa 1 giả định sai + chốt 4 quyết định.

### 11.1 ⚠️ ĐÍNH CHÍNH §1.1 — embed/caption/ingest HIỆN KHÔNG đi qua ai-router
Sơ đồ §1.1 (dòng "caption/embed đi qua ai-router") là **mục tiêu, chưa phải hiện trạng**. Audit code+env chứng minh ngược lại:
- [common.env:29](../../deploy/env/common.env#L29) + [README-ai-router.md:42](../../deploy/monitor_decision/README-ai-router.md#L42): `EMBED_BASE_URL` **rỗng = gọi thẳng OpenAI**.
- **3 luồng AI bypass router** (vô hình với accounting → đây chính là gốc của §8 #5 cost sai):
  1. `mcp-service` embed query (mỗi rag_search) — [embedding.py](../../src/mcp-service/app/core/embedding.py) base_url rỗng.
  2. `rag-worker` embed ingestion — [openai_provider.py](../../src/rag-worker/core_engine/ai/openai_provider.py).
  3. `rag-worker` caption + OCR (vision) — cùng provider.
- Chỉ **query-service LLM chat** (think/triage/guardrail) là đã route + có **CI gate** ([test_llm_architecture_enforcement.py](../../src/query-service/tests/test_llm_architecture_enforcement.py)).

**Remediation "khống chế HẾT" (điều kiện cần cho observability đúng):**
- (a) Trỏ env `EMBED_BASE_URL` + mcp `embed/rerank_base_url` + rag-worker caption/ocr/embed base_url → `http://ai-router:8010/v1` (code đã sẵn sàng, zero code).
- (b) **Thêm CI architecture-gate cho mcp-service + rag-worker** (mirror query-service) → chống hồi quy vĩnh viễn. ĐÂY mới là "khống chế hết" đúng nghĩa, không chỉ là đổi env.
- (c) ⚠️ Caveat: route embed qua router → router thành **critical path của RAG search + ingest**. Cần **fallback graceful** (router lỗi → tạm gọi thẳng) trước khi bật (a).

### 11.2 Cụ thể hoá §7.1 Strategy — selector `weighted_banded` (per-node strategy)
Hiện thực đầu tiên cho "Strategy interface" của §7.1, áp cho node `think`:
- **Backbone:** thêm `selector` optional vào `CapabilityConfig` → strategy **riêng từng capability** (các node khác giữ `sticky_rotation_soft`).
- **Lane = tier + weight + band.** think: lane A `gpt-5.4-mini`@free_oai (weight 4, band **250K**/key, vẫn tôn trọng hard cap 2.5M/key); lane B `deepseek-v4-flash`@OpenRouter (weight 1, band **50K**/key). Weighted round-robin → "cứ ~5 request 1 nhịp deepseek".
- **Counters mới:** `next_seq` (RR, Redis INCR atomic) + band-counter; reserve cũ giữ nguyên.
- Mục tiêu: rải đều key + thử nghiệm deepseek-flash vs gpt-5.4-nano ở chính path tool-calling. **Rủi ro:** deepseek format tool-call khác OpenAI → có thể tái phát leak raw-JSON (xem [chat.ts extractAction đã gia cố](../../src/frontend/chat/app/stores/chat.ts)); GÁC bằng e2e tool-gate trước khi mở master switch.

### 11.3 Ranh giới Langfuse ↔ Grafana (chốt cho §5 vùng Cost + câu 5/6)
- **Grafana = bộ não OPERATIONAL** (độc quyền): cost · token · model · key · capability · routing · quota · RED. Nguồn = accounting của router (cost thật từ catalog), KHÔNG đọc Langfuse.
- **Langfuse = kính hiển vi per-request** (debug 1 hội thoại): prompt · completion · tool calls · session · user · latency · usage. **Không** dùng làm nơi phân tích cost/model (Langfuse cost hiện = $0 do không map giá qua router).
- Nối 2 mặt bằng **`key_id` + `trace_id`** (tag tối thiểu trên trace, chỉ để cross-link, KHÔNG để analytics ở Langfuse).
- Cần: thêm metric router `airouter_calls_total` / `tokens_total` / `cost_usd_total` `{key_id, model, capability, tier, status}` (per-key **× model** — chiều §8 #5 còn thiếu) + table Grafana "Key × Model × Capability".

### 11.4 Chốt phạm vi Control Plane v1 (cụ thể hoá §7.0/§7.0b — bảo thủ hơn)
- **UI:** tab admin trong **frontend Vue hiện có** (tái dùng auth/UX), Grafana chỉ observe + link sang.
- **Quyền v1 = read-only + DRAIN KEY khẩn cấp THÔI.** Pin model / đổi selector **vẫn qua `routing.yaml` + `/admin/reload`** (audit qua git). Override model/selector runtime → để **v2**.
- Hiện thực v1 tối giản: `ovr:key:{id}:state=drain` (Redis, có TTL) + selector bỏ key drain + 2 endpoint `/admin/key/{id}/drain|resume` (internal_token, audit) + tab Vue đọc `/admin/quota`.
- Rào an toàn (cả v1): TTL tự hết hạn · không drain key sống cuối cùng · audit (ai/lúc nào/vì sao) · preview trước commit.

### 11.5 Thứ tự thực thi (nhánh AI Router, bám §6/§9)
1. **Khống chế hết** (11.1 a+b+c) — điều kiện cần.
2. **Per-key×model metrics + Grafana table** (11.3) — để quan sát blend.
3. **weighted_banded + routing.yaml** (11.2) — bật blend, verify bằng (2).
4. **Control Plane v1** (11.4) — drain key + tab Vue.
> (2) phải trước (3): không quan sát được thì bật blend là mù — đúng tinh thần §7.1 "quan sát thiếu thì điều khiển mù".

---

### Phụ lục — dẫn chứng code (file:line) cho Task Inventory
- Query/LangGraph nodes: `query-service/.../orchestration.py`, `.../langgraph_nodes.py`, `.../observability/langfuse_tracing.py`
- Retrieval: `mcp-service/app/core/search.py`, `embedding.py`, `vectorstore.py`, `rerank.py`
- Routing: `ai-router/ai_router/router.py`, `selector/sticky_rotation.py`, `counters.py`, `observability.py`
- Ingest: `rag-worker/app/core/engine.py`, `captioner.py`, `.../use_cases/ingestion/ingest_document_use_case.py`
- Gateway/Auth/Infra: `nginx/nginx.conf`, `user-service/.../auth.py`, `dependencies.py`, `query-service/.../mcp_client.py`, `docker-compose.yml`, `deploy/monitor_decision/`
