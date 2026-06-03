# GAP — rag-service: hiện trạng vs goal

> **Mục đích:** đối chiếu hiện trạng code (`haystack_interface/` + `app/`) với *goal*
> định nghĩa trong [decide/](./decide/) (technique + concise) và [handoff/](./handoff/)
> (CONSTRAINTS, LESSONS, DAY0_CHECKLIST). Trả lời: **còn thiếu gì so với mục tiêu, mức độ
> nghiêm trọng, và thứ tự nên đóng.**
>
> Ngày: 2026-06-03 · Nhánh: `nguyendev` · Phạm vi review: toàn bộ `src/rag-service`.
>
> **Lưu ý đọc:** nhiều ★ trong technique docs là *quyết định v2 còn `PROPOSED`* (chưa
> ratify) — thiếu chúng KHÔNG hẳn là "nợ", mà là "chưa chốt". Gap report phân biệt rõ:
> **(C)** vi phạm/thiếu so với *ràng buộc cứng* (không ★, bắt buộc theo handoff) vs
> **(★)** hạng mục thuộc quyết định chưa ratify.

---

## Quy ước mức độ

| Mức | Ý nghĩa |
|---|---|
| 🔴 **Cao** | Vi phạm ràng buộc cứng (CONSTRAINTS) hoặc chặn chạy production / sai contract |
| 🟡 **Vừa** | Lệch goal đáng kể; cần đóng trước khi lên production thật |
| 🟢 **Thấp** | Đã có nền, còn thiếu hoàn thiện; hoặc thuộc ★ chưa ratify |
| ✅ **Đạt** | Đã làm đúng goal |

---

## 1. Bảng tổng hợp

| # | Khu vực | Goal (nguồn) | Hiện trạng | Mức |
|---|---|---|---|---|
| 1 | Core RAG offline (split→caption→embed→search→rerank) | ingestion §5,6 · search §1 | **Chạy được**, 4 self-test PASS, e2e thật qua OpenRouter OK | ✅ |
| 2 | Kiến trúc hexagonal (port/adapter/composition root) | CONSTRAINTS §1 | `haystack_interface` tuân thủ tốt; engine chỉ phụ thuộc port | ✅ |
| 3 | Cùng embedder/model/dimension ingest==query | search §2 | AI gateway singleton + factory ép dimension | ✅ |
| 4 | Index id encode dimension, reject sai dimension | ingestion §8 | `index_id()=collection__d{dim}` + `_point()` raise | ✅ |
| 5 | Id deterministic (doc→section→vector) | CONSTRAINTS §2 | `{doc}::p{i}::c{j}` + uuid5; **doc_id do caller cấp** (chưa từ địa chỉ nguồn) | 🟢 |
| 6 | Concurrency async-native, không nửa vời | LESSONS §4.1 | async xuyên suốt, sync-client bọc `to_thread`; test concurrency PASS | ✅ |
| 7 | **Response schema = CONTRACT** (lineage + correlation_id) | search §6, CONSTRAINTS §2 | `SearchResult` **thiếu** `lineage.source_uri`, `lineage.artifact_uri`, `correlation_id`, `heading_path` | 🔴 |
| 8 | **Access control là việc của CALLER**, retrieval KHÔNG enforce | LESSONS §1 (discovery), search §6 | ✅ **Đã gỡ** (2026-06-03): bỏ `UserContext`, filter Qdrant, `can_access`, module `access/`, field classification/allowed_* khỏi IngestInput+payload | ✅ |
| 9 | **Fail-closed** ở production; degraded phải thấy được | CONSTRAINTS §2, LESSONS §4.2 | `AI_PROVIDER=auto` → **âm thầm rơi offline** khi thiếu key; store mặc định `:memory:` | 🔴 |
| 10 | Health/readiness phản ánh degraded + backend identity | ingestion §10, search §7 | **Chưa có** endpoint health nào | 🔴 |
| 11 | Tầng API (edge) nối engine | overview, CONSTRAINTS §1 | `app/interfaces/api/routers/*` + `use_cases/*` là **TODO stub**; FastAPI không có endpoint thật | 🔴 |
| 12 | Lazy import SDK, skip-nếu-thiếu | LESSONS §"SDK optional" | `openai` import **top-level** trong `ai/openai_provider.py` → hard-dep cả khi offline; qdrant đã lazy ✅ | 🟡 |
| 13 | Durable job store + atomic claim (Q1/Q2, claim_id) | ingestion §2 | **Chưa có** — không có queue, claim, terminal-status guard | 🟡 (★D1) |
| 14 | Write-order: mark→overwrite→**prune**→complete | ingestion §7, CONSTRAINTS §2 | ✅ **Đã sửa** (commit 7865682): overwrite-then-prune-diff (`list_chunk_ids` → `upsert_many` → `delete_many(stale)`); **chưa** atomic-claim/version guard cho same-doc-concurrent & multi-instance | 🟡 |
| 15 | Canonical artifact (markdown) trước split | ingestion §4 | **Chưa có** — engine nhận sẵn markdown, không lưu artifact, không replay | 🟡 |
| 16 | Parser (MarkItDown + OCR/vision), I/O guard | parser.md, ingestion §3 | **Chưa có** — `azure_doc_intel_client.py` là vỏ; không size-guard/allow-list/path-traversal | 🟡 (★D2) |
| 17 | Change detector (event + reconciliation scanner) | ingestion §1 | **Chưa có** — không S3, không event, không scanner | 🟢 (★D1) |
| 18 | Metadata DB + job log + retention/prune | ingestion §8,10 | **Chưa có** — `postgres_document_repository.py` stub | 🟡 |
| 19 | Embedding coalescer + cache content_hash | ingestion §6 | **Chưa có** — `embed_batch` gọi thẳng, không gom cross-call, không cache, không dedup | 🟢 (★D4) |
| 20 | Hybrid (BM25 + RRF) bù caption-only | search §4 | **Dense-only**; `bm25_text`/`query_text` lưu nhưng không dùng; docstring/demo gọi "RRF" gây hiểu nhầm | 🟢 (★D7) |
| 21 | Eval gate (golden queries + lineage + recall/p95) | search §7, CONSTRAINTS §2 | `eval/pipeline_prototype.ipynb` là prototype; **không có gate** chặn merge | 🟡 |
| 22 | Config validation startup (provider+url+model, model+dim+index) | ingestion §10 | `OpenAIProvider.validate()` chỉ check model+key; **không** validate dim↔index, backend↔credential | 🟡 |
| 23 | Observability: correlation_id, structured log theo stage | ingestion §10 | Dùng `print()`; không correlation_id, không structured log | 🟡 |
| 24 | Cost guardrail (trần AI/OCR, metric cost theo stage) | ingestion §10 | **Chưa có** | 🟢 |
| 25 | Deploy verify (pin digest, verify image/health/migration) | CONSTRAINTS §2 | **Chưa có** Dockerfile/K8s/migration | 🟢 |
| 26 | Contract test chạy trên backend THẬT (không chỉ in-memory) | LESSONS §4 | `_contract.py` chạy qdrant `:memory:`; **chưa** chạy remote Qdrant; chroma/milvus chưa verify | 🟡 |
| 27 | Versioning chống stale-write (out-of-order) | ingestion §7 | **Chưa có** `object_version`/`section_version` | 🟢 (★D6) |
| 28 | No-answer policy (threshold, không bịa) | search §3 | rerank threshold lọc kết quả yếu ✅ | ✅ |

---

## 2. Gap 🔴 Cao — phải xử lý trước khi gọi là "production-ready"

### 2.1 Response schema chưa đủ contract (thiếu lineage + correlation_id) — #7
**Goal:** [search §6](./decide/technique/search.md) + [CONSTRAINTS §2](./handoff/CONSTRAINTS.md): mỗi kết quả **bắt buộc** có
`correlation_id`, `unit_id`, `document_id`, `display_name`, `caption`, `content`,
`heading_path`, `lineage.artifact_uri`, `lineage.source_uri`, `score`. Bỏ field lineage
hay nội dung đầy đủ = **vỡ contract**.

**Hiện trạng** ([vector_repository.py `SearchResult`](../app/domain/repositories/vector_repository.py)):
có `chunk_id`(≈unit_id), `document_id`, `document_name`(≈display_name), `parent_text`(≈content),
`section_title`, `score`. **Thiếu:**
- `correlation_id` (per-request trace) — không có ở đâu trong pipeline.
- `lineage.source_uri` — **bắt buộc để tạo citation**; không có (chưa có S3/nguồn).
- `lineage.artifact_uri` — không có (chưa có canonical artifact).
- `heading_path` (breadcrumb) — chỉ có `section_title` phẳng.
- `caption` như field tường minh — caption bị embed nhưng không lưu riêng để trả về.

**Vì sao Cao:** đây là contract với consumer (Chat/AI service). Thiếu lineage ⇒ tầng trên
không citation được ⇒ phá chính *project intent* ("luôn truy ngược về nguồn gốc").

**Hướng đóng:** mở rộng `SearchResult` + payload ingest để mang `source_uri`, `artifact_uri`,
`heading_path`, `caption`, và truyền `correlation_id` xuyên suốt request. Khi chưa có S3,
ít nhất để field + điền giá trị tạm có ý nghĩa (vd `source_uri = local://{document_id}`),
KHÔNG bỏ field.

### 2.2 Access control bị enforce TRONG retrieval — ✅ ĐÃ XỬ LÝ (2026-06-03) — #8
**Goal:** [LESSONS §1 discovery](./handoff/LESSONS.md) + [search §6](./decide/technique/search.md):
*"retrieval layer single-tenant KHÔNG nên biết tổ chức/role… trả raw unit + lineage. Access
control là việc của caller tầng trên."*

**Đã làm:** gỡ sạch access control khỏi rag-service (chọn "xóa hoàn toàn"):
- Bỏ `UserContext` khỏi [vector_repository.py](../app/domain/repositories/vector_repository.py)
  và toàn bộ chữ ký `search`/`hybrid_search` (port, store facade, provider abstract, 3 provider).
- Gỡ `_access_filter` (qdrant) + `can_access` post-filter (milvus/chroma); bỏ `OVERFETCH` (×5)
  vì không còn post-filter cần bù.
- Xoá module `haystack_interface/access/` (classification.py + __init__.py).
- Bỏ field `classification`/`allowed_departments`/`allowed_user_ids` khỏi `IngestInput`, payload
  ingest, `Document` entity, `IngestRequest`/`SearchRequest` schema.
- Cập nhật demo + 4 self-test + contract test (bỏ ca "classification filter").

**Kết quả:** retrieval trả raw unit + lineage; phân quyền hoàn toàn ở caller tầng trên. Toàn bộ
self-test + demo PASS sau refactor. Nếu sau này cần phân quyền, ingest có thể nhét scope/tags vào
payload như metadata thụ động — nhưng rag-service KHÔNG tự lọc.

### 2.3 Không fail-closed — âm thầm rơi offline / in-memory — #9
**Goal:** [CONSTRAINTS §2](./handoff/CONSTRAINTS.md) + Risk Register #1: *failure nguy hiểm nhất là
"sống nhưng trả kết quả sai mà caller tưởng đúng"*; production thiếu backend chính ⇒ **fail
startup**; mock/in-memory chỉ ở dev/test (explicit).

**Hiện trạng:**
- [`ai/__init__._build_provider`](../haystack_interface/ai/__init__.py): `AI_PROVIDER=auto` →
  thiếu key/base_url ⇒ **OfflineProvider** (hash-embed giả). Nếu production cấu hình sai env,
  hệ vẫn "chạy" với embedding rác → đúng kịch bản cấm.
- [qdrant inprocess](../haystack_interface/vectorstore/providers/qdrant/inprocess.py): thiếu
  `url` ⇒ `:memory:`, mất dữ liệu khi restart — một dạng in-memory-default âm thầm.

**Vì sao Cao:** vi phạm trực tiếp lesson "fail-closed". `auto`-default-offline tiện cho dev nhưng
nguy hiểm cho production.

**Hướng đóng:** thêm cờ môi trường (vd `APP_ENV=production`) → khi production: `AI_PROVIDER`
phải là `openai` thật + `VECTOR_DB_URL` bắt buộc; thiếu ⇒ raise lúc startup. Offline/`:memory:`
chỉ cho `dev`/`test`.

### 2.4 Health/readiness chưa tồn tại — #10
**Goal:** [ingestion §10](./decide/technique/ingestion.md) + [search §7](./decide/technique/search.md):
degraded ⇒ trả `unhealthy` + backend identity + lý do; lộ queue depth/running/coalescer.
**Hiện trạng:** không có endpoint health nào (FastAPI app chỉ include router rỗng).
**Hướng đóng:** thêm `/health` lộ provider name + vector backend + degraded reason; gắn vào
fail-closed (#9).

### 2.5 Tầng API là stub — service chưa chạy được như API — #11
**Goal:** [CONSTRAINTS §1](./handoff/CONSTRAINTS.md): edge layer nối use-case; composition root wire.
**Hiện trạng:** [`routers/search.py`](../app/interfaces/api/routers/search.py),
[`routers/ingest.py`](../app/interfaces/api/routers/ingest.py),
[`use_cases/query/retrieval.py`](../app/application/use_cases/query/retrieval.py),
[`use_cases/ingestion/ingest_document_use_case.py`](../app/application/use_cases/ingestion/ingest_document_use_case.py)
đều là TODO comment. `HaystackRagEngine` **chưa** được wire vào FastAPI. Ngoài ra
[`app/infrastructure/vector/qdrant_vector_repository.py`](../app/infrastructure/vector/qdrant_vector_repository.py)
là stub **trùng vai trò** với `haystack_interface/vectorstore` đã hoàn chỉnh.

**Hướng đóng:** nối `search`/`ingest` router → use-case → `engine` (build ở composition root,
inject qua DI/lifespan). Xoá stub `app/infrastructure/vector` nếu đã được `haystack_interface`
thay thế (tránh hai nguồn sự thật).

---

## 3. Gap 🟡 Vừa — cần trước production thật

- **#12 SDK import top-level.** `from openai import AsyncOpenAI` ở đầu
  [`ai/openai_provider.py`](../haystack_interface/ai/openai_provider.py), bị `ai/__init__` kéo →
  `openai` thành hard-dep cả khi chạy offline. Goal (LESSONS) là lazy import + skip-nếu-thiếu
  như qdrant đã làm. → chuyển import vào trong `__init__`/method.
- **#14 Write-order / prune — ✅ ĐÃ SỬA (commit 7865682).** Engine giờ làm overwrite-then-prune-diff:
  `list_chunk_ids_by_document` → `upsert_many` (đè theo id deterministic) → `delete_many(stale = existing − new)`.
  Đúng [ingestion §7](./decide/technique/ingestion.md) + CONSTRAINTS §2 (không còn delete-rồi-recreate).
  - **Còn thiếu (gắn #13/#27):** flow `list → upsert → delete` **không atomic**. Đã thêm `_op_lock` serialize op
    của qdrant in_process (vì `QdrantClient` local không thread-safe). NHƯNG với **re-ingest cùng document
    đồng thời** hoặc **multi-instance**, vẫn cần guard `claim_id`/`version` trên upsert (ingestion §7) để
    job cũ không ghi đè/xóa nhầm bản mới. An toàn cho tuần tự + single-instance; chưa an toàn cho
    concurrent same-doc / multi-instance.
- **#15/#16 Canonical artifact + Parser chưa có.** Engine nhận markdown sẵn; chưa có bước
  S3→parse→artifact→split. → thuộc ★D2 nhưng cần cho luồng ingest thật; tối thiểu thêm adapter
  `Parser` + lưu artifact để replay rẻ.
- **#18 Metadata DB + job log + retention.** Chưa có; cần cho trạng thái document, lineage, audit.
  Goal cảnh báo "mỗi storage path phải có consumer + retention".
- **#21 Eval gate.** Có notebook prototype, chưa thành gate chặn merge (golden queries + expected
  lineage + recall/precision/no-answer + p50/p95). Goal coi đây là ràng buộc cứng cho mọi thay
  đổi parser/caption/model/index/rerank.
- **#22 Config validation chưa đủ.** `validate()` mới check model+key; thiếu kiểm cặp
  model↔dimension↔index id và backend↔credential lúc startup.
- **#23 Observability.** `print()` thay logging; thiếu `correlation_id`/structured log theo stage —
  liên quan #7 (correlation_id là field contract).
- **#26 Contract test chưa chạy backend thật.** Mới `:memory:`; cần chạy remote Qdrant trong CI để
  chứng minh semantics production (lesson "in-memory không chứng minh production semantics").

---

## 4. Gap 🟢 Thấp / thuộc ★ chưa ratify

- **#20 Hybrid/BM25 + RRF** (★D7): hiện dense-only; rerank bù caption-only đã có. *Cần sửa
  docstring/nhãn* (`engine.py`, port, `demo.py` in `rrf=`) cho khớp README (đang nói "hybrid RRF"
  trong khi chạy dense) — đây là nợ *tài liệu*, dễ gây hiểu nhầm.
- **#17 Change detector / S3 event** (★D1), **#19 coalescer+cache** (★D4), **#24 cost guardrail**,
  **#25 deploy/K8s**, **#27 versioning anti-stale-write** (★D6): đều là quyết định v2 `PROPOSED`,
  chưa ratify — thiếu là *đúng kế hoạch*, không phải nợ; ratify trước khi implement.
- **#5 document_id từ địa chỉ nguồn:** hiện caller cấp; khi có S3 sẽ dẫn xuất `f(địa chỉ nguồn)`.

---

## 5. Điểm đã đạt tốt (giữ nguyên)

- Core RAG offline chạy ngay, 4 self-test + e2e thật PASS.
- Hexagonal sạch: engine chỉ phụ thuộc port; SDK nằm trong adapter; composition root tập trung ở
  `factory.py`; provider-first registry + lazy import (qdrant/chroma/milvus).
- Bất biến "dimension store = dimension embedder" ép bằng kiến trúc; index id encode dimension;
  upsert reject sai dimension.
- AI gateway một-điểm-vào, reliability policy (retry+backoff+jitter) đồng nhất.
- Contract test dùng chung backend-agnostic (conformance MOSA).
- async-native nhất quán (đúng Lesson concurrency), test chứng minh không chặn event loop.

---

## 6. Thứ tự đóng đề xuất (ưu tiên giảm dần)

1. ~~**Quyết định access-control (#8)**~~ — ✅ XONG (2026-06-03): đã gỡ access control khỏi
   rag-service; retrieval trả raw unit + lineage.
2. **Bổ sung field contract còn thiếu (#7)** — `correlation_id` + `lineage.*` + `heading_path` +
   `caption`; điền giá trị tạm khi chưa có S3.
3. **Fail-closed + health (#9, #10)** — gate `APP_ENV=production`, raise khi thiếu backend chính,
   `/health` lộ identity + degraded.
4. **Nối API ↔ engine (#11)** + xoá stub trùng (`app/infrastructure/vector`).
5. ~~**Prune trong write-order (#14)**~~ ✅ XONG (commit 7865682) — còn atomic-claim guard (gắn #13/#27). + **config validation đủ (#22)** + ~~lazy import openai (#12)~~ ✅.
6. **Eval gate (#21)** + **contract test remote Qdrant (#26)** + **observability/correlation (#23)**.
7. **Ratify ★ rồi implement:** parser+artifact (#15/#16), metadata DB (#18), coalescer (#19),
   hybrid (#20), versioning (#27), cost guardrail (#24), deploy (#25).

---

## 7. Truy vết

- Goal: [decide/concise.md](./decide/concise.md) · [decide/technique/ingestion.md](./decide/technique/ingestion.md) ·
  [decide/technique/search.md](./decide/technique/search.md) · [handoff/CONSTRAINTS.md](./handoff/CONSTRAINTS.md) ·
  [handoff/LESSONS.md](./handoff/LESSONS.md) · [decide/NEW_REPO_DECISIONS.md](./decide/NEW_REPO_DECISIONS.md)
- Hiện trạng: [haystack_interface/README.md](../haystack_interface/README.md) (§"Capability gap",
  §"Giới hạn đã biết" — tác giả đã tự thừa nhận một phần các gap trên) · code `haystack_interface/` + `app/`.
