# GAP — rag-service: hiện trạng vs goal

> **Mục đích:** đối chiếu hiện trạng code (`haystack_interface/` + `app/`) với *goal*
> định nghĩa trong [decide/](./decide/) (technique + concise) và [handoff/](./handoff/)
> (CONSTRAINTS, LESSONS, DAY0_CHECKLIST). Trả lời: **còn thiếu gì so với mục tiêu, mức độ
> nghiêm trọng, và thứ tự nên đóng.**
>
> Tạo: 2026-06-03 · Nhánh: `nguyendev` · Phạm vi: toàn bộ `src/rag-service`.
> **Cập nhật gần nhất: 2026-06-04** sau loạt commit `bc0d502 → b0aceb2` (enforce contract,
> fail-closed+health, wire API, safe prune, access-control removal, metadata DB+alembic,
> structured logging). Các 🔴 ban đầu (#7–#11) đã đóng — xem §2.
>
> **Lưu ý đọc:** nhiều ★ trong technique docs là *quyết định v2 còn `PROPOSED`* (chưa
> ratify) — thiếu chúng KHÔNG hẳn là "nợ", mà là "chưa chốt".

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
| 1 | Core RAG offline (split→caption→embed→search→rerank) | ingestion §5,6 · search §1 | **Chạy được**, self-test + e2e thật qua OpenRouter OK | ✅ |
| 2 | Kiến trúc hexagonal (port/adapter/composition root) | CONSTRAINTS §1 | `haystack_interface` tuân thủ tốt; engine chỉ phụ thuộc port | ✅ |
| 3 | Cùng embedder/model/dimension ingest==query | search §2 | AI gateway singleton + factory ép dimension | ✅ |
| 4 | Index id encode dimension, reject sai dimension | ingestion §8 | `index_id()=collection__d{dim}` + `_point()` raise | ✅ |
| 5 | Id deterministic (doc→section→vector) | CONSTRAINTS §2 | `{doc}::p{i}::c{j}` + uuid5; **doc_id do caller cấp** (chưa từ địa chỉ nguồn) | 🟢 |
| 6 | Concurrency async-native, không nửa vời | LESSONS §4.1 | async xuyên suốt, sync-client bọc `to_thread`; test concurrency PASS | ✅ |
| 7 | **Response schema = CONTRACT** (lineage + correlation_id) | search §6, CONSTRAINTS §2 | ✅ **Đã làm** (bc0d502): `SearchResult` + `SearchResultResponse` đủ `correlation_id`/`unit_id`/`display_name`/`caption`/`content`/`heading_path`/`lineage.{source,artifact}_uri`/`score`; nối engine→mapper→schema→router; có pytest | ✅ |
| 8 | **Access control là việc của CALLER**, retrieval KHÔNG enforce | LESSONS §1 (discovery), search §6 | ✅ **Đã gỡ**: bỏ `UserContext`, filter Qdrant, `can_access`, module `access/`, field classification/allowed_* | ✅ |
| 9 | **Fail-closed** ở production; degraded phải thấy được | CONSTRAINTS §2, LESSONS §4.2 | ✅ **Đã làm** (45b28df): `APP_ENV=production` + offline/in_process ⇒ raise startup; dev/test degraded; có pytest | ✅ |
| 10 | Health/readiness phản ánh degraded + backend identity | ingestion §10, search §7 | ✅ **Đã làm** (45b28df): `/health` trả `ai_provider`/`vector_*`/`reasons`, degraded ⇒ 503 | ✅ |
| 11 | Tầng API (edge) nối engine | overview, CONSTRAINTS §1 | ✅ **Đã làm** (7865682, 90fbc2a): `POST/GET/DELETE /api/ingest` + `POST /api/search` → use-case → engine; bootstrap inject qua lifespan; stub `app/infrastructure/vector` đã rỗng/không còn ai import | ✅ |
| 12 | Lazy import SDK, skip-nếu-thiếu | LESSONS §"SDK optional" | ✅ **Đã làm**: `openai` import cục bộ trong `_client()` + `TYPE_CHECKING`; `ai/__init__` lazy qua `__getattr__`; factory dùng `provider.name`; đường offline không kéo `openai` | ✅ |
| 13 | Durable job store + atomic claim (Q1/Q2, claim_id) | ingestion §2 | **Chưa có** — không queue/claim/terminal-status guard. Ingest chạy inline đồng bộ | 🟡 (★D1) |
| 14 | Write-order: mark→overwrite→**prune**→complete | ingestion §7, CONSTRAINTS §2 | ✅ **Đã sửa** (7865682): overwrite-then-prune-diff; `_op_lock` serialize qdrant in_process. **Còn** atomic-claim/version cho same-doc-concurrent & multi-instance (gắn #13/#27) | 🟡 |
| 15 | Canonical artifact (markdown) trước split | ingestion §4 | **Chưa có** — engine nhận sẵn markdown, không lưu artifact, không replay | 🟡 |
| 16 | Parser (MarkItDown + OCR/vision), I/O guard | parser.md, ingestion §3 | **Chưa có** — `azure_doc_intel_client.py` là vỏ; không size-guard/allow-list/path-traversal | 🟡 (★D2) |
| 17 | Change detector (event + reconciliation scanner) | ingestion §1 | **Chưa có** — không S3, không event, không scanner | 🟢 (★D1) |
| 18 | Metadata DB + job log + retention/prune | ingestion §8,10 | ✅ `DocumentRepository` (InMemory + Postgres), **Alembic migration**, index `created_at`, **job-log table + append/list/prune API + prune runner theo lịch + lifecycle policy doc** đã có | ✅ |
| 19 | Embedding coalescer + cache content_hash | ingestion §6 | **Chưa có** — `embed_batch` gọi thẳng, không gom cross-call/cache/dedup | 🟢 (★D4) |
| 20 | Hybrid (BM25 + RRF) bù caption-only | search §4 | **Dense-only** (★ chưa ratify); nhãn/docstring đã sửa cho khớp (hết "rrf="). Rerank bù caption-only đã có | 🟢 (★D7) |
| 21 | Eval gate (golden queries + lineage + recall/p95) | search §7, CONSTRAINTS §2 | ✅ **Có gate tối thiểu**: `tests/eval/test_golden_queries.py` kiểm lineage + top-hit recall + no-answer; **p95 chỉ assert khi bật provider thật** qua env. **Còn** CI wiring với provider thật / dataset rộng hơn | 🟡 |
| 22 | Config validation startup (provider+url+model, model+dim+index) | ingestion §10 | ✅ **Phần lớn đã đóng đúng constraint hiện tại**: `runtime` validate `EMBED_DIMENSION`/`SEARCH_TOP_K`/`RERANK_TOP_K`/split bounds/provider/collection naming/remote url/**remote credential policy**; AI provider thật fail-fast ở `provider.validate()`. **Còn** các ràng buộc backend-specific sâu hơn nếu thêm backend mới | 🟢 |
| 23 | Observability: correlation_id, structured log theo stage | ingestion §10 | ✅ **Đã làm** (3729d09 + 3abbd04): `log_event` + `JsonLogFormatter` (stdlib) bật ở composition root; event kèm `correlation_id`/`stage`/counts; hết `print()` | ✅ |
| 24 | Cost guardrail (trần AI/OCR, metric cost theo stage) | ingestion §10 | **Chưa có** | 🟢 |
| 25 | Deploy verify (pin digest, verify image/health/migration) | CONSTRAINTS §2 | **Chưa có** Dockerfile/K8s | 🟢 |
| 26 | Contract test chạy trên backend THẬT (không chỉ in-memory) | LESSONS §4 | ✅ **Có test opt-in**: `tests/haystack_interface/test_qdrant_remote_contract.py` chạy remote Qdrant khi có `QDRANT_URL`/`VECTOR_DB_URL`. **Còn** wiring vào CI và mở rộng sang backend khác | 🟡 |
| 27 | Versioning chống stale-write (out-of-order) | ingestion §7 | **Chưa có** `object_version`/`section_version` | 🟢 (★D6) |
| 28 | No-answer policy (threshold, không bịa) | search §3 | rerank threshold lọc kết quả yếu ✅ | ✅ |

---

## 2. 🔴 ban đầu — ĐÃ ĐÓNG

Loạt vi phạm ràng buộc cứng / chặn-production ban đầu nay đã xử lý (kèm pytest):

- **#7 Response schema contract** (bc0d502) — `SearchResult`/`SearchResultResponse` đủ field
  contract (search §6): `correlation_id` (per-request, echo mỗi result), `unit_id`, `document_id`,
  `display_name`, `caption`, `content`, `heading_path`, `lineage.{source,artifact}_uri`, `score`.
  Nối xuyên engine → vector mapper (3 provider) → API schema → router. Khi chưa có S3, `source_uri`
  điền tạm `local://{document_id}` — KHÔNG bỏ field.
- **#8 Access control** — gỡ sạch khỏi retrieval (LESSONS §1 discovery): bỏ `UserContext`, filter
  Qdrant pre-filter, `can_access` post-filter, module `access/`, và field classification/allowed_*.
  Phân quyền hoàn toàn ở caller tầng trên.
- **#9 Fail-closed + #10 Health** (45b28df) — `bootstrap_runtime`: `APP_ENV=production` mà provider
  offline / vector in_process ⇒ **raise startup**; dev/test chạy nhưng `/health` trả `unhealthy`
  (503) kèm `ai_provider`/`vector_provider`/`vector_deployment`/`vector_index`/`reasons`.
- **#11 API ↔ engine** (7865682, 90fbc2a) — `POST /api/search`, `POST/GET/DELETE /api/ingest`
  + `GET /api/ingest` (list) → use-case → engine, wire ở composition root (`runtime.lifespan`).
  Stub `app/infrastructure/vector/qdrant_vector_repository.py` nay rỗng/không còn ai import.
- **#12 Lazy import SDK** — `openai` không còn import top-level (cục bộ trong `_client()` +
  `TYPE_CHECKING`); `ai/__init__` lazy `__getattr__`; factory dùng `provider.name`. Đường offline
  không kéo `openai`.
- **#14 Write-order/prune** (7865682) — overwrite-then-prune-diff thay cho delete-rồi-recreate
  (đúng ingestion §7 / CONSTRAINTS §2).

> **Không còn 🔴 blocker.** Rủi ro cao nhất còn lại nằm ở 🟡: an toàn concurrent (#13/#14-atomic),
> eval gate (#21), config validation chưa đủ (#22), contract test backend thật (#26).

---

## 3. 🟡 Vừa — cần trước production thật

- **#13 + #14 (atomic-claim).** Prune đã đúng write-order, nhưng flow `list → upsert → delete`
  **không atomic**; `_op_lock` chỉ serialize trong một process. Re-ingest cùng document đồng thời /
  multi-instance vẫn cần guard `claim_id`/`version` trên upsert (ingestion §7) + durable job store
  (ingestion §2). Ingest hiện chạy **inline đồng bộ** trong HTTP request — khi thêm queue phải đổi
  sang enqueue job.
- **#15/#16 Canonical artifact + Parser.** Engine nhận markdown sẵn; chưa có S3→parse→artifact→split.
  Thuộc ★D2 nhưng cần cho luồng ingest thật; tối thiểu thêm adapter `Parser` + lưu artifact (replay rẻ).
- **#18 Metadata DB.** Đã đóng cho phạm vi hiện tại: repo + alembic migration + index `created_at`
  + **bảng job-log / append-list-prune API / prune job theo lịch / lifecycle policy doc**. Phần còn
  liên quan metadata status concurrency nằm ở #13.
- **#21 Eval gate.** Đã có **gate tối thiểu** bằng pytest (golden queries + expected lineage +
  no-answer). Bản mặc định chạy offline để chứng minh plumbing; khi bật provider thật qua env mới
  dùng nó như gate chất lượng/p95 production.
- **#22 Config validation.** Đã đóng phần runtime cốt lõi cho backend hiện có: bounds/provider/
  collection naming/remote url/AI credential/remote vector credential policy. Chỉ còn rule sâu hơn
  nếu mở rộng thêm backend/provider mới.
- **#26 Contract test backend thật mới ở mức opt-in.** Đã có test remote Qdrant qua env; còn đưa vào CI
  thường trực và mở rộng sang backend khác (lesson "in-memory không chứng minh production semantics").

---

## 4. 🟢 Thấp / thuộc ★ chưa ratify

- **#20 Hybrid/BM25 + RRF** (★D7): hiện dense-only; rerank bù caption-only đã có; nhãn/docstring đã
  sửa cho khớp (không còn gọi "rrf"). Implement hybrid là việc sau khi ratify.
- **#17 Change detector / S3 event** (★D1), **#19 coalescer+cache** (★D4), **#24 cost guardrail**,
  **#25 deploy/K8s**, **#27 versioning anti-stale-write** (★D6): quyết định v2 `PROPOSED`, chưa
  ratify — thiếu là *đúng kế hoạch*; ratify trước khi implement.
- **#5 document_id từ địa chỉ nguồn:** hiện caller cấp; khi có S3 sẽ dẫn xuất `f(địa chỉ nguồn)`.

---

## 5. Điểm đã đạt tốt (giữ nguyên)

- Core RAG offline chạy ngay; self-test + e2e thật PASS.
- Hexagonal sạch: engine chỉ phụ thuộc port; SDK trong adapter; composition root tập trung; registry
  provider-first + lazy import.
- Bất biến dimension store = dimension embedder; index id encode dimension; upsert reject sai dimension.
- AI gateway một-điểm-vào, reliability policy (retry+backoff+jitter) đồng nhất; marker rerank dùng chung
  (prompt ↔ offline parser không drift).
- Contract test backend-agnostic (conformance MOSA) + test guard cho fail-closed/health/contract/rerank/migration.
- Structured logging JSON active với correlation_id.
- async-native nhất quán; test chứng minh không chặn event loop.

---

## 6. Thứ tự đóng đề xuất (cho phần còn lại)

1. **Atomic-claim + durable job (#13, hoàn tất #14/#18-status)** — guard `claim_id`/`version` trên
   upsert + job store persist; cần cho concurrent same-doc / multi-instance an toàn.
2. **Config validation đủ (#22)** — kiểm `model↔dimension↔index id`, `backend↔credential` lúc startup (rẻ, đúng constraint).
3. **Eval gate (#21)** + **contract test remote Qdrant (#26)** — chặn regression chất lượng + chứng minh semantics production.
4. **Parser + canonical artifact (#15/#16)** — mở luồng ingest thật từ S3/OCR; thêm I/O guard.
5. **Cost guardrail (#24)**.
6. **Ratify ★ rồi implement:** change detector (#17), coalescer (#19), hybrid (#20), versioning (#27), deploy (#25).

> Đã đóng (không cần làm lại): #7, #8, #9, #10, #11, #12, #14 (prune), #18, #23.

---

## 7. Truy vết

- Goal: [decide/concise.md](./decide/concise.md) · [decide/technique/ingestion.md](./decide/technique/ingestion.md) ·
  [decide/technique/search.md](./decide/technique/search.md) · [handoff/CONSTRAINTS.md](./handoff/CONSTRAINTS.md) ·
  [handoff/LESSONS.md](./handoff/LESSONS.md) · [decide/NEW_REPO_DECISIONS.md](./decide/NEW_REPO_DECISIONS.md)
- Hiện trạng: [haystack_interface/README.md](../haystack_interface/README.md) · code `haystack_interface/` + `app/` ·
  test `tests/` (pytest) + `haystack_interface/tests/` (self-test scripts).
