# VSF RAG Chatbot — Internal Q&A + HR Assistant

RAG chatbot nội bộ cho doanh nghiệp: nhân viên hỏi chính sách/tài liệu công ty và tự thao tác HR
(xin nghỉ, xem công, lương) qua hội thoại tự nhiên, trả lời **stream theo thời gian thực (SSE)** kèm
trích dẫn nguồn. Kiến trúc multi-agent + LLM gateway tách lớp, vận hành full CI/CD với health-gate +
auto-rollback. Production: **https://vsfchat.cloud** (1 GCP VM, docker-compose).

> Tài liệu chi tiết, **verify trực tiếp từ code** (không phải spec lý thuyết): xem [docs/](docs/).

---

## Vì sao đáng xem

Đây không phải "demo RAG nối OpenAI SDK". Vài quyết định kỹ thuật cụ thể đã đo bằng số liệu thật,
không phải lý thuyết:

- **LLM gateway tách riêng (`ai-router`)** — mọi service gọi LLM/embedding qua 1 cổng OpenAI-compatible
  duy nhất, route theo "capability alias" (không hardcode tên model), quota/cost theo Redis, failover
  nhiều provider (OpenAI/OpenRouter). Đổi model production = sửa 1 file YAML, không sửa code agent.
- **Multi-agent Orchestrator-Workers (LangGraph)** — câu hỏi đơn đi thẳng `light path`; câu hỏi phức
  tạp (đa chủ đề, cần nhiều tool) fan-out ra `worker` song song rồi `verify_answer` tổng hợp + chấm
  citation. Bỏ 1 LLM call thừa (`worker distill`) sau khi đo regression → giảm latency câu nặng **53%**,
  giữ accuracy ~75% — quyết định dựa trên A/B thật, không suy đoán.
- **Contract-first giữa các service** — SSE event, NATS subject, JWT claims, embedding dimension đều có
  1-nguồn-sự-thật + gate trong CI (sai hợp đồng → build đỏ trước khi lên prod), không phải convention
  ngầm dễ vỡ khi nhiều người cùng sửa.
- **Deploy có rollback tự động** — mỗi lần deploy ghi điểm "image đang chạy" trước khi pull bản mới;
  health-gate + smoke test (chọn lọc theo service đổi) fail ở bất kỳ bước nào → tự retag về bản cũ,
  production không bao giờ đứng yên ở bản hỏng.
- **Đã load-test thật, không chỉ chạy local**: 450 câu hỏi/60s mô phỏng giờ cao điểm — 0 lỗi 5xx/timeout,
  85% SUCCESS, nhưng cũng đo ra trần thật của hệ thống (đa-agent chậm hơn rõ rệt) và biết chính xác
  nghẽn ở đâu để fix tiếp, thay vì tuyên bố "scale tốt" mà không có số.

---

## Kiến trúc

```
                          Cloudflare TLS
                               │
                          nginx :80  ──/admin/──> frontend-admin (Nuxt 4)
        /───────────────────┬─┴───────────────────\        └/──> frontend-chat (Nuxt 4)
 /api/user      /api/documents   /api/query (×8)   /api/hr     /api/mcp
    │                 │               │               │           │
user-service    document-service   query-service   hr-service   mcp-service
                       │ GCS upload      │  │                        │
                       │ NATS doc.ingest │  └─ MCP ──> mcp-service ──┴─ HTTP /api/search ──> rag-worker ──> Qdrant
                       ▼                 │                           └─ HTTP proxy (internal token) ──> hr-service
              rag-ingest-worker (×8)     └─ OpenAI SDK (base_url) ──> ai-router ──> OpenAI / OpenRouter
                  embed via ai-router
```

**8 service ứng dụng** (mỗi service: 1 DB riêng, container riêng, scale độc lập):

| Service | Vai trò |
|---|---|
| `query-service` (×8 replica) | Orchestrate hội thoại — LangGraph orchestrator-workers, stream SSE |
| `ai-router` | Gateway LLM/embedding OpenAI-compatible — chọn model/provider theo capability, quota Redis |
| `mcp-service` | MCP tool server: `rag_search`, `hr_query`, `leave_write/approvals/types`, `resolve_date` |
| `rag-worker` (+ ingest-worker ×8) | Ingest (OCR/chunk/embed) + retrieval (`/api/search`) trên Qdrant |
| `hr-service` | Sở hữu dữ liệu nhân sự (lương/nghỉ/công), internal-only |
| `document-service` | Vòng đời tài liệu — upload → GCS, ACL theo phòng ban |
| `user-service` | Auth/JWT |
| `frontend-chat` / `frontend-admin` | 2 Nuxt 4 micro-frontend, dùng chung base layer (auth + design system) |

Hạ tầng: **Qdrant** (vector), **Postgres** (database-per-service), **Redis** (memory hội thoại + quota),
**NATS JetStream** (event bus: doc/hr/user/notify), **GCS** (lưu file), **Langfuse** (LLM trace),
**Grafana/Prometheus** (metrics).

> Chi tiết đầy đủ + sơ đồ mermaid: [docs/architecture/overview.md](docs/architecture/overview.md) ·
> [docs/architecture/ai-architecture.md](docs/architecture/ai-architecture.md) (luồng multi-agent) ·
> [docs/architecture/data-flow.md](docs/architecture/data-flow.md) (chat + ingest end-to-end).

---

## Tech stack

| Lớp | Công nghệ |
|---|---|
| Agent orchestration | LangGraph (orchestrator-workers), Model Context Protocol (MCP) |
| LLM/embedding | OpenAI-compatible gateway tự viết (`ai-router`), provider OpenAI + OpenRouter |
| Backend | FastAPI (Python), kiến trúc theo domain/use-case mỗi service |
| Vector DB | Qdrant |
| Messaging | NATS JetStream |
| DB | PostgreSQL (database-per-service), Redis |
| Frontend | Nuxt 4 (Vue 3), 2 micro-frontend dùng chung base layer |
| Observability | Langfuse (LLM trace), Grafana + Prometheus (metrics) |
| Infra/CI-CD | Docker Compose (1 VM), GitHub Actions — detect-path → validate chọn lọc → build → deploy với health-gate + auto-rollback |

---

## Quick Start (local)

```bash
git clone <repo-url> && cd DA08-VSF-AI

# copy env mẫu cho từng service rồi điền API key thật
cp src/user-service/.env.example       src/user-service/.env
cp src/document-service/.env.example   src/document-service/.env
cp src/query-service/.env.example      src/query-service/.env
cp src/rag-worker/.env.example         src/rag-worker/.env
cp src/frontend/chat/.env.local.example   src/frontend/chat/.env.local
cp src/frontend/admin/.env.local.example  src/frontend/admin/.env.local
# mcp-service / hr-service / ai-router cấu hình qua config.yaml + routing.yaml (override bằng ${VAR})
# chi tiết biến môi trường: docs/ops/env-setup.md

docker compose up --build
```

Sau khi lên: Chat http://localhost:3000 · Admin http://localhost:3001 ·
API docs: `:8000/docs` (user) · `:8001/docs` (query) · `:8002/docs` (document) · `:8004/docs` (hr, internal).

---

## Đo đạc thật (không phải claim)

- **Load test giờ cao điểm** (450 query/60s, mô phỏng ~2× nhịp 1200-user): 0 lỗi 5xx/timeout,
  85% SUCCESS, TTFT p50=19.7s/p95=46.4s. Multi-agent path chậm hơn rõ rệt (p95 74s) — điểm cần
  tối ưu tiếp, không che giấu. Chi tiết: [docs/eval/load-benchmark.md](docs/eval/load-benchmark.md).
- **Retrieval recall** (corpus 120 tài liệu HR-VN + 480 câu gold, embedding qwen3-8b @4096):
  recall@1=**0.73**, recall@3=0.86, MRR=0.80 — đo qua harness riêng, tách khỏi lỗi tầng orchestrator
  phía trên. Số liệu + phương pháp: [systemeval/benchmark.md](systemeval/benchmark.md).
- **Quyết định kiến trúc bằng số liệu, không bằng cảm tính**: đã build xong multi-collection shard
  (4 embedding model) nhưng đo ra recall@1 chỉ 0.53 (model phụ kéo điểm xuống) so với single qwen8b
  0.73 → **chọn single-model cho production**, giữ lại hạ tầng multi để bật khi có model phụ đủ mạnh.
- **Tối ưu pipeline có đo regression**: bỏ 1 bước LLM dư per-worker (`worker distill`), gộp việc trích
  xuất vào bước verify chính → latency câu nặng **-53%**, accuracy giữ ~75%.

---

## Tài liệu

Bộ doc được **rebuild từ code** (mỗi file có `last-verified` + `code-refs` trỏ đúng source) — không
phải spec viết trước rồi để lệch dần. Bản đồ đầy đủ: [docs/README.md](docs/README.md).

| Mảng | Vào nhanh |
|---|---|
| Kiến trúc | [overview](docs/architecture/overview.md) · [ai-architecture](docs/architecture/ai-architecture.md) · [data-flow](docs/architecture/data-flow.md) |
| Từng service | [docs/services/](docs/services/) (1 file/service) |
| Hợp đồng liên-service | [docs/contracts/](docs/contracts/) (SSE, API, NATS, JWT, embedding — đều có CI gate) |
| Vận hành | [deployment](docs/ops/deployment.md) · [ci-cd](docs/ops/ci-cd.md) · [env-setup](docs/ops/env-setup.md) |
| Đánh giá | [docs/eval/](docs/eval/) |
| Nhật ký phát triển (theo commit) | [docs/journal/](docs/journal/) — quá trình thật, kể cả sai-sửa, không tô vẽ |

---

## Đội ngũ (6 người)

| Vai trò | Phụ trách |
|---|---|
| Solution Architect | Domain model, contracts, schema, review |
| Frontend Dev | Nuxt 4 chat/admin/base |
| Backend Dev | user-service, document-service, NATS infra |
| RAG Engineer | rag-worker, mcp-service, hr-service |
| AI/Agent Engineer | query-service (multi-agent orchestration) |
| DevOps | Infra, CI/CD, GCP |

Chi tiết phân công file: [docs/ops/team-ownership.md](docs/ops/team-ownership.md).
