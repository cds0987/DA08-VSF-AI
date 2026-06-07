# GAP v6 - rag-worker: job lifecycle durability & ingest-path hardening

Scope: only `src/rag-worker` (ingest pipeline, job repository, NATS consumer, S3 parser, API).
Grounding: code review verified against current `nguyendev` HEAD.
Updated: 2026-06-07
Status: **CLOSED** — cả 8 gap đã fix & verify. Commits:
- `8397086` *Fix rag-worker ingest job durability gaps* — G6-1..G6-8.
- `2bbfced` *Harden rag-worker migration upgrade path* — dedup trước unique index (G6-3),
  sửa mojibake error string (G6-5), khôi phục comment rationale consumer.

Test xác nhận: `pytest tests/infrastructure/db/test_postgres_document_repository.py
test_migration.py tests/interfaces/nats/test_ingest_consumer.py tests/infrastructure/test_s3_parser.py
tests/interfaces/api/test_ingest_router.py tests/application/ingestion/test_ingest_document_use_case.py`
→ **55 passed, 1 skipped**.

## Điểm mạnh hiện có (giữ nguyên, không regress khi fix)

- **Optimistic-lock job claiming**: `SELECT` + conditional `UPDATE` với `rowcount == 1`
  (`postgres_document_repository.py:299-318`) → concurrent workers không double-claim.
- **Heartbeat + stale-reaper**: `renew_claim` (`:323`) + `mark_stale_jobs` (`:339`) recover
  worker chết mà không cần can thiệp tay.
- **`BadPayloadError` (→ NATS term) vs transient (→ NAK)**: `ingest_consumer.py:70` phân biệt
  poison message với lỗi tạm, tránh retry vô hạn cho payload sai cấu trúc.
- **S3 download 5 lớp guard**: HEAD size check, stream-to-disk, byte counter giữa chừng,
  cleanup trong `finally` (`s3_parser.py:228-258`).
- **Production fail-closed at startup**: cấu hình AI/DB sai → hard raise.

## Gaps đã xác minh & đóng

| ID | Mức | Vấn đề | Cách fix | Trạng thái |
|---|---|---|---|---|
| G6-1 | 🔴 CRITICAL | Stale-reaper không có attempt cap → poison job loop vô hạn | `INGEST_MAX_ATTEMPTS` + `_fail_jobs_exceeding_max_attempts` (claim + reaper) → job vượt ngưỡng sang `FAILED`, đồng bộ document + job_log | ✅ Fixed `8397086` |
| G6-2 | 🟠 HIGH | `delete()` không xóa `ingest_jobs` + `job_logs` → orphan chặn re-ingest | `_delete_sync` xóa cả `job_logs` + `ingest_jobs` + `documents` theo `document_id` | ✅ Fixed `8397086` |
| G6-3 | 🟠 HIGH | Dedup `find_active_job()` non-atomic → double job | Unique partial index `ux_ingest_jobs_active_document_id` + `add`/`flush`/bắt `IntegrityError`; migration dedup duplicate cũ trước khi tạo index | ✅ Fixed `8397086` + `2bbfced` |
| G6-4 | 🟠 HIGH | `document_name` không giới hạn vs DB `String(512)` → NAK storm | Reject `doc_id` >255; truncate `document_name` >512 (warn) tại consumer | ✅ Fixed `8397086` |
| G6-5 | 🟡 MEDIUM | `ContentLength=0`/missing bypass HEAD guard | `size <= 0` → reject sớm (sửa cả mojibake error string) | ✅ Fixed `8397086` + `2bbfced` |
| G6-6 | 🟡 MEDIUM | `DELETE /ingest/{document_id}` không auth | `INGEST_DELETE_API_KEY` opt-in qua header `X-API-Key` | ✅ Fixed `8397086` |
| G6-7 | 🟡 MEDIUM | `update_status(PROCESSING)` xóa `error_message` | Chỉ clear error khi `COMPLETED`; giữ khi PROCESSING | ✅ Fixed `8397086` |
| G6-8 | 🔵 LOW | `_artifact_path()` chỉ sanitize `/` và `\` | Whitelist `[A-Za-z0-9_-]{1,120}`, fallback sha256 | ✅ Fixed `8397086` |

> Parity: `inmemory_document_repository.py` mirror đầy đủ logic Postgres (attempt cap, delete
> cascade, error preservation) — test 2 backend đồng nhất.

> ⚠️ Deploy note: migration `0002` set duplicate active job cũ sang `FAILED` với message
> `"superseded by migration before active-job unique index"`. Sau khi chạy trên Cloud SQL, đếm
> số dòng này để biết prod có duplicate thật hay không.

---

## Chi tiết (mô tả trạng thái TRƯỚC fix — giữ làm rationale)

> Line numbers dưới đây là của bản trước fix (HEAD lúc review). Sau commit `8397086`/`2bbfced`
> vị trí dòng đã đổi — xem bảng trên để biết cách fix thực tế.

### 🔴 G6-1. Stale-reaper không có attempt cap → poison job loop vô hạn

`_mark_stale_jobs_sync` (`:339`) chuyển mọi job `PROCESSING` quá hạn về `STALE`, và
`_claim_next_pending_sync` (`:283`) lại nhặt `STALE` lên `PROCESSING` (tăng `attempt` ở `:310`).
Cột `attempt` được **tăng nhưng không bao giờ được kiểm tra**. Một job làm worker crash
(OOM, segfault parser, panic) sẽ chạy vòng `PENDING → PROCESSING → (crash) → STALE → PROCESSING`
mãi mãi — không bao giờ đạt terminal `FAILED`, vừa kẹt 1 slot worker vừa lặp lại chi phí.

**Fix**: tại claim (`:299`) thêm điều kiện `attempt < MAX_ATTEMPTS`; job vượt ngưỡng thì
reaper (hoặc claim path) set `FAILED` với `error_message="exceeded max attempts"` thay vì requeue.
Ngưỡng đọc từ env (vd `INGEST_MAX_ATTEMPTS`, default 5).

### 🟠 G6-2. `delete()` để lại orphaned `ingest_jobs` + `job_logs`

`delete()` (`:195-197`) chỉ gọi `vectors.delete_by_document` + `documents.delete`. Hàng trong
`ingest_jobs`/`job_logs` không bị xóa. Re-ingest cùng `document_id` sau đó bị `find_active_job()`
(`:260`) bắt gặp job non-terminal cũ (PENDING/PROCESSING/STALE) → bỏ qua như "duplicate" →
document không bao giờ được ingest lại.

**Fix**: mở rộng `delete()` xóa cả `ingest_jobs` và `job_logs` theo `document_id` trong cùng
transaction với xóa document (hoặc thêm `ON DELETE CASCADE`).

### 🟠 G6-3. Dedup `find_active_job()` non-atomic → double job

`find_active_job()` (`:59`) là `SELECT` thuần rồi mới `enqueue()` ở app layer. Hai NATS delivery
đồng thời (at-least-once) cùng `document_id` đều thấy "không có active job" → tạo 2 PENDING job →
double embedding cost + vector set không nhất quán. Models hiện chỉ có `index=True` trên
`document_id` (`models.py:47`), **không có unique partial index** — đúng như TODO trong code.

**Fix**: thêm unique partial index `(document_id) WHERE status IN ('PENDING','PROCESSING','STALE')`
ở DB; insert job bắt `IntegrityError` → coi như duplicate, trả job hiện có.

### 🟠 G6-4. `document_name` không cap độ dài → integrity error → NAK storm

`ingest_consumer.py:89` lấy `document_name = payload.get("document_name") or doc_id` không giới
hạn; DB cột `name`/`document_name` là `String(512)` (`models.py:17,48`). Payload name > 512 ký tự
→ integrity error khi insert → NAK → một poison message retry storm vô hạn (đây là lỗi
"transient" theo phân loại nên KHÔNG bị term như `BadPayloadError`).

**Fix**: validate/truncate `document_name` (và kiểm `doc_id` ≤ 255) ở consumer; quá dài thì
truncate có cảnh báo, hoặc raise `BadPayloadError` để term thay vì NAK.

### 🟡 G6-5. `ContentLength=0`/missing bypass HEAD guard

`s3_parser.py:232` `size = int(head.get("ContentLength", 0))`; header thiếu/0 → bỏ qua check
ở `:233`. Object multi-GB sẽ stream xuống đĩa cho tới khi counter giữa chừng (`:249`) chặn —
guard mid-stream **vẫn bắt được**, nên đây là defense-in-depth bị thủng một lớp, không phải lỗ
hổng hoàn toàn.

**Fix**: coi `ContentLength` thiếu/≤0 là đáng ngờ → từ chối sớm, hoặc log cảnh báo và dựa hẳn
vào mid-stream guard (đã có).

### 🟡 G6-6. `DELETE /ingest/{document_id}` không authentication

`ingest.py:77-83` xóa toàn bộ vector + metadata mà không có auth. Bất kỳ caller nào reach được
port này đều xóa được dữ liệu.

**Fix**: nếu endpoint này expose ngoài internal network, thêm auth dependency (API key/token).
Nếu chỉ internal (compose network), document rõ ràng giả định trust boundary này.

### 🟡 G6-7. `update_status(PROCESSING)` xóa lịch sử lỗi

`_update_status_sync` (`:120-124`) luôn set `record.error_message = error`; gọi với `PROCESSING`
(error=None, vd `process_next_job():114`) sẽ ghi đè `error_message` của lần fail trước → mất
post-mortem cho document bị retry.

**Fix**: chỉ clear `error_message` ở transition thành công (COMPLETED), giữ nguyên khi chuyển
sang PROCESSING (cập nhật có điều kiện hoặc tham số `clear_error`).

### 🔵 G6-8. `_artifact_path()` sanitize chưa đầy đủ

`local_artifact_store.py:19` chỉ replace `/` và `\`. Vì mọi separator bị thay nên path traversal
qua `..` thực tế **không** thoát được root (read path còn có `_resolve_artifact_path` check
`relative_to(root)` ở `:29`), nhưng các ký tự path-special khác (null byte, control chars) trên
write path không được neutralize → tên file lạ/lỗi OS.

**Fix**: whitelist ký tự cho `document_id` (alnum + `-_`), hoặc hash document_id để đặt tên file.

---

## Ưu tiên đề xuất

1. **G6-1** (CRITICAL) — chặn vòng lặp vô hạn ăn slot worker.
2. **G6-2 / G6-3 / G6-4** (HIGH) — đều liên quan tính đúng đắn của vòng đời job & dedup; nên fix
   cùng đợt với migration thêm unique partial index.
3. **G6-5..G6-8** (MEDIUM/LOW) — hardening, làm sau.

---

## Trước khi fix: dev BẮT BUỘC đọc gì (tránh làm vỡ codebase)

> Codebase này có **constraint cứng** (vi phạm = technical debt/bug production, không phải style).
> Đọc theo thứ tự, rồi map vào gap mình định fix.

### Đọc nền (mọi gap đều cần)

1. **[handoff/CONSTRAINTS.md](../handoff/CONSTRAINTS.md)** — ràng buộc cứng. Đặc biệt:
   - *Section 1 Dependency Direction*: use-case layer KHÔNG import SDK; model core KHÔNG import
     framework/ORM. Mọi I/O qua capability contract.
   - *Section 4 Pre-Commit Checklist* (17 câu): tự trả lời TRƯỚC khi commit, "no" nào → không merge.
2. **[handoff/MINDSET.md](../handoff/MINDSET.md)** — vocabulary trung tính (vai trò layer) để hiểu
   CONSTRAINTS nói về lớp nào.
3. **[handoff/NEW_REPO_DECISIONS.md](../handoff/NEW_REPO_DECISIONS.md)** — nếu fix đụng quyết định
   Day-0 (vd retry policy, schema), phải cập nhật file này trước khi merge.

### Map tài liệu ↔ từng gap

| Gap | PHẢI đọc thêm | Constraint dễ vi phạm khi fix |
|---|---|---|
| **G6-1** attempt cap | CONSTRAINTS §2 "Thứ tự ghi để giữ consistency", §2 "Fallback"; checklist #7 | Set `FAILED` phải ghi job log + cập nhật document status; không leak slot concurrency ở finally |
| **G6-2** delete orphans | CONSTRAINTS §2 "Document id generation" (idempotent reprocess), §2 "Thứ tự ghi"; checklist #8 | Xóa phải để re-ingest cùng `document_id` idempotent; không phá thứ tự ghi-đè-trước-prune-sau |
| **G6-3** unique partial index | CONSTRAINTS §3 "Schema + migration" (migration có version, idempotent, có index bắt buộc); checklist #15 | KHÔNG `CREATE INDEX` ad-hoc trong code — phải qua migration có rollback note; xem [infra/scripts/init-db.sql](../../../../infra/scripts/init-db.sql) |
| **G6-4** name length cap | CONSTRAINTS §2 "Security/resource guards"; phân biệt `BadPayloadError`(term) vs transient(NAK) ở [ingest_consumer.py](../../app/interfaces/nats/ingest_consumer.py); checklist #10 | Validate ở edge layer (consumer), không nhét vào use-case; thêm test poison message |
| **G6-5** ContentLength guard | CONSTRAINTS §2 "Security/resource guards của I/O nguồn" (size-before-read, guard dùng chung sync+async); checklist #11 | Sửa guard phải giữ allow-list + path-traversal + size-before-read; review như security-sensitive |
| **G6-6** DELETE auth | CONSTRAINTS §2 "Runtime Boundaries"; [docs/api-spec.md](../../../../docs/api-spec.md), [docs/contracts.md](../../../../docs/contracts.md) | Auth là contract với caller — cập nhật doc contract + thông báo consumer (checklist #4) |
| **G6-7** error history | CONSTRAINTS §2 "Health/readiness phản ánh degraded state"; checklist #5,#7 | Giữ error_message để post-mortem; không che degraded state |
| **G6-8** artifact sanitize | CONSTRAINTS §2 "Security/resource guards" (chặn path traversal); checklist #11 | Giữ check `relative_to(root)` ở read path; thêm whitelist write path |

### Nếu fix đụng pipeline (parser/splitter/embedding/index/search)

→ checklist #13: phải chạy **eval gate** (golden queries + expected source lineage) trước khi merge.
Xem [search-split-vectorstore-contract.md](../search-split-vectorstore-contract.md). G6-1..G6-8 hiện
**không** đụng retrieval semantics, nhưng nếu fix lan sang vector write thì gate này bắt buộc.

---

## Luồng CI + Git flow hiện tại

> Nguồn: [.github/workflows/](../../../../.github/workflows/). 3 workflow đang chạy.

### Branch model

```
nguyendev  ──(push)──►  CI: rag-service-ci.yml  (test + contract + search-semantic)
                                  │ xanh
                                  ▼
                        PR / merge vào  develop
                                  │
develop    ──(push)──►  deploy-develop.yml  ──SSH──►  GCP VM: git reset --hard origin/develop
                                                       docker compose up --build -d
main       = nhánh ổn định (PR thường nhắm main theo policy repo)
```

- **Branch dev hiện tại**: `nguyendev`. Push lên đây kích hoạt CI test.
- **`develop`**: push vào = **tự deploy thẳng lên GCP VM** ([deploy-develop.yml](../../../../.github/workflows/deploy-develop.yml)).
  ⚠️ Cẩn thận: deploy `git reset --hard origin/develop` + `docker compose up --build`. Đừng push
  code chưa xanh CI vào `develop`.
- **`main`**: nhánh chính cho PR (theo cấu hình repo).

### CI: [rag-service-ci.yml](../../../../.github/workflows/rag-service-ci.yml)

Trigger: push lên `nguyendev` khi đổi `src/rag-worker/**`, `src/mcp-service/**`, hoặc chính workflow.
Python 3.13. 3 job:

1. **`contract`** — `scripts/check_vectorstore_contract.py` so `config.yaml` của rag-worker vs
   mcp-service. Lệch vectorstore contract = fail ngay (không cần hạ tầng).
2. **`test`** — dựng **hạ tầng thật bằng docker**: NATS JetStream (`-js`), MinIO (S3), Qdrant.
   - Suite chính: `pytest tests -q -ra --ignore=tests/e2e` (NATS OFF, `AI_PROVIDER=offline`).
   - E2e: `pytest tests/e2e` với NATS+MinIO+Qdrant thật.
3. **`search-semantic`** — luồng 2 service thật: rag-worker seed cả corpus vào Qdrant
   (`seed_validation_corpus_e2e.py`), mcp-service search lại; có cả case **drift phải fail-closed**.

**Hệ quả cho dev fix G6-x:**
- Test chạy `AI_PROVIDER=offline` → fix không được phụ thuộc provider thật.
- DB: CI dùng Postgres? **Lưu ý** — workflow này dựng NATS/MinIO/Qdrant nhưng *không* thấy Postgres
  service; job repository test có thể dùng SQLite/in-memory. G6-1/G6-2/G6-3 đụng `ingest_jobs` →
  kiểm tra test fixture DB trước, đảm bảo migration (partial index) chạy được trên cả CI và Cloud SQL.
- Thêm test cho fix: suite chính phải pass với hạ tầng off; test cần broker đặt trong `tests/e2e`.

### [e2e-cloud.yml](../../../../.github/workflows/e2e-cloud.yml)

E2e trên hạ tầng cloud (xem các commit `e2e-cloud` gần đây nối query-service qua MCP search). Chạy
khi đụng luồng liên service — fix G6-6 (DELETE API) nếu đổi contract nên kiểm workflow này.

### Quy trình đề xuất khi fix một gap

1. Branch từ `nguyendev` (hoặc theo policy team).
2. Đọc tài liệu map ở trên + chạy `pytest tests -q --ignore=tests/e2e` local (`AI_PROVIDER=offline`).
3. Gap đụng schema (G6-3) → viết migration có version + rollback note, không sửa bảng ad-hoc.
4. Trả lời Pre-Commit Checklist (CONSTRAINTS §4).
5. Push → CI xanh (`contract` + `test` + `search-semantic`) → PR.
6. **Không** đẩy vào `develop` cho tới khi PR review xong (push develop = auto-deploy VM).

---

## References

- [CONSTRAINTS.md](../handoff/CONSTRAINTS.md)
- [rag-service-ci.yml](../../../../.github/workflows/rag-service-ci.yml)
- [deploy-develop.yml](../../../../.github/workflows/deploy-develop.yml)
- [gap5.md](./gap5.md)
- [ingest_document_use_case.py](../../app/application/use_cases/ingestion/ingest_document_use_case.py)
- [postgres_document_repository.py](../../app/infrastructure/db/postgres_document_repository.py)
- [ingest_consumer.py](../../app/interfaces/nats/ingest_consumer.py)
