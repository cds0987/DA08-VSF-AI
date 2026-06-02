# Overview technique — điểm vào toàn pipeline

> Mô tả cho 2 sơ đồ tổng quan:
> - [../diagram/overview.mermaid](../diagram/overview.mermaid) — **bản chốt**, end-to-end, cross-cutting đặt ngay trong stage nó tác động.
> - [../diagram/overview-compact.mermaid](../diagram/overview-compact.mermaid) — 1 nhìn, rút gọn.
>
> Đây là **điểm vào**; chi tiết cách làm + đặc tính vận hành nằm ở 3 doc dưới.

## Cấu trúc (khớp overview.mermaid)

| Nhóm trong diagram | Thành phần | Doc chi tiết |
|---|---|---|
| **Source** | Object store / S3 | [ingestion.md](./ingestion.md) §0 |
| **Change Detector** ★ | Event Listener (primary) + Reconciliation Scanner (safety net) | [ingestion.md](./ingestion.md) §1 · [scaling.md](./scaling.md) §6 |
| **File Task Intake** | Queue 1 (durable) + Atomic Claim + Config Validation (fail-fast) | [ingestion.md](./ingestion.md) §2,10 · [scaling.md](./scaling.md) §2,3 |
| **Tier 1 — Parse / Split** (CPU-heavy) | Parser Worker × N: download · convert/OCR · parse · split | [ingestion.md](./ingestion.md) §3,5 |
| **Canonical + Section Tasks** | Artifact Store (Markdown) + Queue 2 (durable) + Atomic Claim | [ingestion.md](./ingestion.md) §4 |
| **Tier 2 — Index / Upsert** (I/O-bound) | Index Worker × M: build caption · request vector · upsert | [ingestion.md](./ingestion.md) §6,7 |
| **Shared Embedding Layer** | Coalescer + Cache (content_hash) + Provider | [ingestion.md](./ingestion.md) §6 · [scaling.md](./scaling.md) §4 |
| **Stores** | Qdrant + Metadata DB + Health/Readiness (fail-closed) | [ingestion.md](./ingestion.md) §8 · schema [search.md](./search.md) §6 |
| **Failure** | Dead Letter Queue → status + job log | [ingestion.md](./ingestion.md) §9 · [scaling.md](./scaling.md) §5 |

**Quyết định trình bày đã chốt:** cross-cutting đặt *trong* stage nó tác động (`Config Validation` ở File Task Intake; `Health` ở Stores) thay vì gom vào một box "Ops" rời. Dễ đọc hơn, đúng ngữ cảnh.

Luồng ĐỌC (search) không nằm trong overview ingest — xem [../diagram/search.mermaid](../diagram/search.mermaid) + [search.md](./search.md).

## Bất biến không được phá

- đơn vị retrieve = **section nghĩa**, không token-chunk
- embed **caption**, index **content** đầy đủ + lineage
- **canonical artifact** trước split → replay rẻ
- **durable queue + atomic claim (claim_id)** 2 tầng → không mất job, không race
- **fail-closed + health phản ánh degraded**, failure không im lặng
- response schema là **contract** — bảng field chuẩn ở [search.md](./search.md) §6

## Chi tiết bị lược trong overview (vẫn là yêu cầu — tra technique docs)

Overview cố tình gọn; những điểm sau KHÔNG hiện trên hình nhưng bắt buộc:

- `★` Event Listener + **versioning chống stale-write** (event out-of-order) → [scaling.md](./scaling.md) §2,6
- **I/O guard** (size-before-read · path traversal · allow-list) trong Parser → [ingestion.md](./ingestion.md) §3
- **Coalescer bounds/drain/metrics** + cache in-memory không cross-process → [ingestion.md](./ingestion.md) §6 · [scaling.md](./scaling.md) §4
- **DLQ phân loại** (stage · transient/permanent · retry_count) → [scaling.md](./scaling.md) §5
- `★` **content_ref** (section lớn) + **rerank/hybrid** (bù caption-only) → [search.md](./search.md) §4,5
- **write-order** atomic-safe replace (overwrite → prune → complete) → [ingestion.md](./ingestion.md) §7

## Ký hiệu

**Không ★** = grounded trong [../../handoff/](../../handoff/). **★** = quyết định v2 ngoài/để-ngỏ → ghi `PROPOSED` vào `NEW_REPO_DECISIONS.md` (danh sách ★ ở cuối mỗi technique doc).
