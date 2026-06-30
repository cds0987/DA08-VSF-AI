# Docs — DA08-VSF-AI

Tài liệu hệ thống RAG chatbot HR (prod `https://vsfchat.cloud`). **Nguyên tắc: code là bằng chứng
duy nhất** — mọi file dưới đây verify trực tiếp từ code/compose (mỗi file có frontmatter
`last-verified` + `code-refs:` trỏ file nguồn). Tài liệu rebuild từ code tại commit `59551e39`
(2026-06-29). Khi code đổi, sửa file tương ứng + bump `last-verified`.

## Bản đồ

### architecture/ — hệ thống tổng thể
| File | Nội dung |
|---|---|
| [overview.md](architecture/overview.md) | Topology 1-VM, 8 service + hạ tầng, ai gọi ai, deployment |
| [data-flow.md](architecture/data-flow.md) | 2 luồng chính: CHAT (SSE) + INGEST (mermaid + bước) |
| [ai-architecture.md](architecture/ai-architecture.md) | MOSA orchestrator-workers, graph node, capability routing |
| [contracts.md](architecture/contracts.md) | Bản 1 trang: nguyên tắc single-source + 7 CI gate (trỏ contracts/) |

### services/ — 1 file/service (verify từ code)
| Service | Tóm tắt |
|---|---|
| [ai-router](services/ai-router.md) | Gateway LLM/embed: resolve capability → selector chọn key/model → failover, quota Redis |
| [query-service](services/query-service.md) | Điều phối MOSA, stream SSE; chat `POST /query`. ⚠️ MOSA default-OFF (`mode: react`) |
| [rag-worker](services/rag-worker.md) | Ingest (parse/OCR/chunk/embed/index) + `POST /api/search`. Prod single qwen8b |
| [mcp-service](services/mcp-service.md) | MCP server thin: tools rag_search / hr_query / leave_write / resolve_date |
| [hr-service](services/hr-service.md) | Payroll/leave/attendance; tạo đơn nghỉ + duyệt trừ quỹ; taxonomy luật LĐ VN |
| [document-service](services/document-service.md) | Upload → GCS/S3, preview office→PDF, ACL department lấy sống từ hr-service |
| [user-service](services/user-service.md) | Auth/JWT (HS256). `department` đã DROP khỏi token/DB |
| [frontend](services/frontend.md) | 3 app Nuxt 4 (chat/admin/base); tiêu thụ SSE, agent tree, document viewer |

### contracts/ — hợp đồng liên-service (verify từ nguồn sự thật + CI gate)
| File | Seam |
|---|---|
| [sse-contract.md](contracts/sse-contract.md) | Event SSE chat + done-event bất biến (gen TS, CI diff) |
| [api-spec.md](contracts/api-spec.md) | HTTP seam hr-service (đơn nghỉ) + endpoint chính per service |
| [nats-events.md](contracts/nats-events.md) | 9 subject NATS (doc.*, hr.*, user.*, notify.*) |
| [jwt-claims.md](contracts/jwt-claims.md) | Claims token; gap: department KHÔNG trong token |
| [embed-models.md](contracts/embed-models.md) | Chuỗi gate embeddings.yaml ⊆ contract ⊆ routing ⊆ catalog |

### ops/ — vận hành (procedural; đối chiếu infra/ + docker-compose khi dùng)
[runbook](ops/runbook.md) · [deployment](ops/deployment.md) · [env-setup](ops/env-setup.md) ·
[ci-cd](ops/ci-cd.md) · [team-access](ops/team-access.md)

### eval/ — đánh giá
[load-benchmark](eval/load-benchmark.md) (sức chịu tải 800-1200 user) ·
[golden-dataset](eval/golden-dataset.md) · [eval-plan](eval/eval-plan.md).
Phương pháp test + số liệu thực đo (đã gom gọn, không còn code harness): `systemeval/testdesign.md`
+ `systemeval/benchmark.md`.

### archive/ — lịch sử (KHÔNG phải sự thật hiện tại)
Plan cũ, gap-iteration, sprint, doc bản nháp trước refactor. Giữ để tra cứu, **đừng tin là khớp code**.

---
> Lưu ý: lần rebuild này phát hiện nhiều docs cũ đã lệch code (vd `/api/query/query` → thật là `/query`;
> rag-worker "ingest-only" → đã có `/api/search`; department còn trong token → đã bỏ). Các file mới đã
> sửa theo code. Chi tiết drift: xem git log của lần refactor docs này.
