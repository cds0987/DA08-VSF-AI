# Canonical Schema — Semantic Conventions (từ điển chung observability)

> **Blocker #1.** Mọi span/metric/log của MỌI service phải dùng đúng tên field ở đây.
> Dev KHÔNG tự đặt tên. Theo chuẩn OpenTelemetry; field tùy biến dùng prefix `vsf.`.
> Trạng thái: chuẩn v1 — sửa qua PR (track history). Liên quan `observability-plan.md` §3.

## 0. Nguyên tắc
- **Tên field = snake_case có namespace** (vd `llm.tokens.input`), không viết tắt tùy hứng.
- **Dùng lại chuẩn OTel** khi có (`http.*`, `service.*`, `db.*`); cái riêng của hệ → `vsf.*`.
- **trace_id xuyên suốt**: sinh tại nginx (W3C `traceparent`), mọi service truyền tiếp — KHÔNG đặt ID riêng.
- **Bắt buộc (M) / Tùy chọn (O)**: cột "M/O" cho biết span có *phải* mang field đó không.
- **PII**: field đánh dấu 🔒 phải scrub tại Collector trước khi lưu (xem §6).

---

## 1. Field chung — MỌI span đều mang
| Field | Kiểu | M/O | Ý nghĩa |
|---|---|:--:|---|
| `service.name` | string | M | tên service (vsf-query-service, ai-router…) |
| `task.name` | string | M | tên task chuẩn (xem §2, vd `retrieval.vector_search`) |
| `task.status` | enum | M | `ok` \| `error` \| `degraded` |
| `duration_ms` | int | M | thời gian task (latency) |
| `request.id` | string | M | = trace_id W3C, xuyên suốt mọi chặng |
| `vsf.env` | string | M | `prod` \| `dev` |
| `error.type` | string | O | loại lỗi khi status=error |

## 2. Danh sách `task.name` chuẩn (khớp Task Inventory plan §1.2)
```
gateway.request
auth.login · auth.verify_token · auth.acl_allowed_docs
query.guardrail · query.triage · query.think · query.semantic_cache
retrieval.embed_query · retrieval.vector_search · retrieval.rerank · retrieval.rag_search
llm.generate
output.guardrail_redact · output.validate
airouter.resolve · airouter.reserve · airouter.call_provider · airouter.account
ingest.parse · ingest.chunk · ingest.caption · ingest.embed · ingest.qdrant_write
```

## 3. Người dùng / phiên (cho câu hỏi ③ "ai & bao nhiêu")
| Field | Kiểu | M/O | Ghi chú |
|---|---|:--:|---|
| `user.id` | string | M | định danh user (KHÔNG dùng key_id/role lẫn lộn) |
| `user.role` | string | M | vai trò (sales/hr/admin…) |
| `user.department` | string | O | phòng ban |
| `session.id` | string | O | gom hội thoại |
| `vsf.conversation_title` | string | O | 🔒 có thể chứa nội dung nhạy cảm |

## 4. LLM / Routing (cho câu ⑤ chi phí, ⑥ chất lượng)
| Field | Kiểu | M/O | Ghi chú |
|---|---|:--:|---|
| `llm.provider` | string | M | openai / openrouter |
| `llm.model` | string | M | gpt-5.4-nano… |
| `llm.key_id` | string | M | định danh key (oai-1) — KHÔNG lộ key thật |
| `llm.tier` | string | M | free_oai / free_or / paid |
| `llm.tokens.input` | int | M | token input |
| `llm.tokens.output` | int | M | token output |
| `llm.tokens.cached` | int | O | cache-read token |
| `cost.usd` | float | M | chi phí task (pay-per-use) |
| `cost.type` | enum | M | `pay_per_use` \| `infra` |
| `vsf.router.fallback` | bool | O | có rơi tier ưu tiên không |
| `vsf.prompt_version` | string | O | version prompt (truy lỗi theo prompt) |

## 5. Retrieval / Embedding / Quality (cho câu ⑥ + kịch bản §5b)
| Field | Kiểu | M/O | Ghi chú |
|---|---|:--:|---|
| `embedding.model` | string | M | text-embedding-3-small… |
| `embedding.tokens` | int | M | token embed (HIỆN THIẾU — bổ sung Phase 2) |
| `retrieval.hits` | int | M | số tài liệu lấy được |
| `retrieval.top_score` | float | M | điểm cao nhất (đủ ngưỡng?) |
| `retrieval.collection` | string | M | collection Qdrant |
| `rerank.model` | string | O | model rerank (nếu LLM) |
| `vsf.quality.groundedness` | float | O | answer bám tài liệu (Phase 5) |
| `vsf.quality.relevance` | float | O | tài liệu liên quan câu hỏi (Phase 5) |
| `vsf.feedback` | int | O | 👍=1 / 👎=-1 (Phase 5) |

## 6. Metric naming (Prometheus)
- **Per-service RED**: `vsf_requests_total{service,task,status}`, `vsf_request_duration_seconds{service,task}`, `vsf_errors_total{service,task}`.
- **Cost**: `vsf_cost_usd_total{service,task,llm_model,llm_tier,cost_type}`.
- **AI Router (đã có, GIỮ)**: `airouter_key_tokens_today`, `airouter_key_cost_month_usd`, `airouter_key_remaining`, `airouter_key_rpm`, `airouter_key_cooldown`, `airouter_key_limit`, `airouter_keys_total`, `airouter_resolve_total`, `airouter_fallback_total`, `airouter_resolve_fail_total`.
  - **THÊM Phase 2**: `airouter_key_input_tokens`, `airouter_key_output_tokens` (tách input/output per-key).
- **Infra (exporter)**: dùng nguyên metric `node_*` (node-exporter), `container_*` (cAdvisor) — không đổi tên.

## 7. PII redaction (scrub tại OTel Collector trước khi lưu)
Field 🔒 phải scrub: `vsf.conversation_title`, nội dung câu hỏi/answer trong span input/output, mọi field HR (lương, CCCD, ngày sinh, địa chỉ). Quy tắc: **trace toàn bộ (sample 100%) NHƯNG che nội dung nhạy cảm**. Cấu hình ở Collector `attributes` processor (delete/hash).

## 8. Sample & retention (quyết định MVP)
| Signal | Sample | Retention | Lưu |
|---|---|---|---|
| trace | 100% | 7d | Tempo (≤4GB RAM, spill disk) |
| log | 100% | 14d | Loki (≤4GB RAM, spill disk) |
| metric | — | 15d | Prometheus |

## 9. Cách dùng (cho dev)
1. Gắn span tên đúng `task.name` (§2).
2. Set field bắt buộc (M) ở §1 + nhóm liên quan task.
3. KHÔNG sinh ID riêng — lấy trace context từ request (`traceparent`).
4. Field mới chưa có ở đây → đề xuất qua PR sửa file này (không tự thêm rời rạc).
