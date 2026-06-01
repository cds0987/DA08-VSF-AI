# V2_HANDOFF.md

> Bản handoff thực dụng để khởi động lại project ở version 2. Distill từ `docs/handoff/` (README, MINDSET, CONSTRAINTS, LESSONS, DAY0_CHECKLIST, NEW_REPO_DECISIONS, PORTING_GUIDE).
>
> Nguyên tắc đọc: **V1 là evidence, không phải template.** Mọi structure/naming/workflow cũ chỉ là dấu vết lịch sử. Chỉ reuse khi có lý do rõ ràng được support bởi handoff files.

---

## 1. Project Intent

Biến một kho tài liệu hỗn tạp (PDF scan, office docs, HTML, ảnh) thành **một lớp retrieval mà tầng tiêu thụ phía trên có thể tin tưởng để grounding**, và luôn truy ngược được về nguồn gốc. Khớp theo *ý định* (semantic) chứ không phải *từ khoá*, trả về *đơn vị tri thức hoàn chỉnh* kèm lineage — không trả mảnh văn bản bị cắt giữa câu.

---

## 2. Prototype V1: Những vấn đề cần tránh

Chỉ giữ các vấn đề ảnh hưởng trực tiếp tới v2:

- **Async nửa vời:** edge async nhưng mọi blocking I/O bị đẩy vào *một* threadpool mặc định chung → CPU-heavy (parse/OCR) và đường serving (search) giẫm chân nhau; kèm một loạt bug lifecycle (exception trong fire-and-forget bị nuốt, orphan future, leak concurrency slot, drain sai thứ tự lúc shutdown).
- **Fallback im lặng ở production:** rơi sang mock/in-memory/file rồi vẫn báo ok → "sống nhưng trả kết quả sai". Cờ cho-phép-mock **default bật**.
- **Claim không an toàn:** claim kiểu đọc-rồi-ghi không lock, không có attempt/claim id → job cũ ghi đè trạng thái job mới khi chạy >1 instance.
- **Queue chỉ in-memory:** job mất sạch khi restart trước khi được claim.
- **Lớp compat/legacy nằm trên runtime path:** composition root vẫn import factory store từ shim (gap đã biết, chưa đóng).
- **Tin "CI xanh = production chạy code mới":** từng deploy xanh nhưng pod chạy code cũ do image không pin đúng.
- **Config sai chỉ lộ ở runtime:** provider/base URL/model name sai, embedding dimension không khớp index → 401 / mismatch lúc request thật.
- **Retrieval unit = đơn vị kỹ thuật (token-chunk):** xé một đơn vị tri thức thành nhiều mảnh thiếu đầu thiếu đuôi.
- **Storage write-only:** tạo bảng/schema (vd `document_chunks`) ghi vào nhưng không ai đọc.
- **Thiếu retention/lifecycle:** job-log phình vô hạn; rename nguồn để lại metadata orphan.
- **OCR không có trần chi phí:** tài liệu visual không text-layer rất đắt/chậm, dễ chạm timeout.

---

## 3. Non-negotiable Constraints

### Technical Constraints
- **Chiều phụ thuộc một chiều:** `edge → use-case → contract ← adapter → model core`. Use-case layer & model core **không import SDK vendor**; model core **không import framework web/ORM/SDK**. Adapter không gọi ngược use-case.
- **Composition root là nơi DUY NHẤT** chọn implementation theo environment + wire. Edge không tự build client.
- **Lớp compat/legacy không nằm trên runtime path chính** (factory chính tắc thuộc composition root/adapter, không thuộc shim).
- **Id deterministic:** document id theo *địa chỉ nguồn*; id con theo id cha + thứ tự; id vector dẫn xuất từ id con. Đổi sang random/content-hash = migration, không phải code edit.
- **Thứ tự ghi giữ consistency:** mark *đang xử lý* → ghi-đè dữ liệu chính (id deterministic) → *prune phần thừa* → mark *hoàn tất* → metadata → job log. **Không delete-rồi-recreate**; không mark hoàn tất trước khi bước cuối thành công.
- **Embedding dimension ↔ index binding:** định danh index encode dimension; ghi sai dimension phải raise. Đổi dimension = migration (reindex/cutover/rollback).
- **Security guard I/O nguồn:** allow-list nguồn, chặn path traversal, **validate size TRƯỚC khi đọc body vào memory**. Guard dùng chung cho mọi path (sync + async).

### Product Constraints
- **Search response schema là contract với consumer:** mỗi kết quả đủ `unit_id` + `document_id` + `display_name` + `caption` (tóm tắt) + `content` (*nội dung đầy đủ*) + `heading_path` + **cả hai lineage URI** (`lineage.artifact_uri` + `lineage.source_uri`) + `score` + `correlation_id` (per-request). Không bỏ field, không đổi tên, không trả tóm tắt thay nội dung; breaking ⇒ version hoá + báo consumer trước. Bảng field chuẩn: [technique/search.md](technique/search.md) §6.
- **Retrieval unit là đơn vị có nghĩa** (theo cấu trúc tài liệu), không phải token-chunk.
- **Embed ý-nghĩa-nén (caption), index & trả full content** — vector và payload là hai thứ khác nhau.

### Process Constraints
- **Fail-closed ở production:** thiếu backend chính ⇒ fail startup. Health/readiness báo *unhealthy* khi degraded (không phải ok), lộ backend identity + lý do.
- **Deploy verification:** pin image bằng tag/digest bất biến (không `latest`); verify image thật đang chạy + health + migration state sau rollout. "CI xanh" không phải bằng chứng.
- **Runtime config compatibility gate:** validate các cặp config liên quan lúc startup, fail-fast cho production.
- **Pipeline quality/eval gate:** mọi thay đổi parser/splitter/caption/embedding/index/rerank/search policy phải qua bộ eval tối thiểu (golden queries + expected source lineage). "Trông đúng khi thử tay" không đủ.
- **Migration versioned, không ad-hoc:** index trong migration; entrypoint dùng `exec` để app nhận signal.

### AI-Agent Workflow Constraints
- **Mỗi quyết định Day 0 phải ở trạng thái `DECIDED` hoặc `DEFERRED` (có owner + điều kiện revisit)** trước khi implement — không "để sau tính" cho mục ảnh hưởng dữ liệu/runtime/bảo mật/chi phí/contract.
- **Mọi quyết định kiến trúc phải ghi vào `NEW_REPO_DECISIONS.md`** (không để quyết định chỉ nằm trong code hoặc chat).
- **Không dán quyết định của prototype vào repo mới như thể đã chốt** — prototype là nguồn học, không phải authority.

---

## 4. Core Lessons Learned

### Lesson: Quyết định concurrency model một lần, dứt khoát
- **Vấn đề trong v1:** chọn "async + offload mọi blocking I/O sang threadpool chung" → nửa vời, threadpool saturation, nhiều bug lifecycle tốn nhiều phiên để vá.
- **Vì sao quan trọng:** quyết định này định hình toàn bộ I/O layer; sửa sau rất đắt vì kéo theo cả dependency stack.
- **Cách áp dụng trong v2:** chọn **async-native** (làm phần consistency trước, chấp nhận dependency risk) HOẶC **sync + executor riêng có giới hạn cho từng loại việc**. Không nửa vời. Tách executor cho bước CPU-heavy (parse/OCR) khỏi đường serving.

### Lesson: Production phải fail-closed, degraded phải nhìn thấy được
- **Vấn đề trong v1:** fallback im lặng sang mock/in-memory; cờ cho-phép-mock default bật.
- **Vì sao quan trọng:** failure nguy hiểm nhất của hệ retrieval là "sống nhưng sai mà caller tưởng đúng".
- **Cách áp dụng trong v2:** default fail-fast khi thiếu backend chính; mock/in-memory chỉ ở dev/test (explicit); health báo unhealthy + lý do khi degraded.

### Lesson: Atomic claim + attempt id thiết kế từ schema
- **Vấn đề trong v1:** claim đọc-rồi-ghi không lock, terminal status không gắn "ai đang xử lý" → job cũ ghi đè job mới.
- **Vì sao quan trọng:** lỗi này chỉ lộ ở backend thật dưới concurrency / multi-instance, rất khó debug.
- **Cách áp dụng trong v2:** atomic upsert/conditional-update; updated_at đổi khi acquire claim; ghi terminal-status có điều kiện khớp claim id + check số dòng ảnh hưởng.

### Lesson: Test in-memory không chứng minh production semantics
- **Vấn đề trong v1:** coi test pass trên in-memory là proof; nhưng in-memory/file/real không behavior-equivalent (durability, claim-race, dimension).
- **Vì sao quan trọng:** bug nguy hiểm nhất chỉ lộ ở backend thật.
- **Cách áp dụng trong v2:** viết **contract test dùng chung** chạy trên cả in-memory lẫn backend thật cho mọi contract có semantics khó (claim, prune, dimension).

### Lesson: Delivery là một phần của hệ thống
- **Vấn đề trong v1:** deploy xanh nhưng pod chạy code cũ do image không pin đúng.
- **Vì sao quan trọng:** debug sai phiên bản đốt thời gian nhất, vì mọi tín hiệu bề mặt đều "xanh".
- **Cách áp dụng trong v2:** pin SHA/digest; verify image + health + migration sau rollout từ Sprint 1.

### Lesson: Config runtime là contract
- **Vấn đề trong v1:** provider/base URL/model/dimension mismatch chỉ lộ ở request đầu tiên.
- **Vì sao quan trọng:** đây là lỗi cấu hình phát hiện được sớm, không nên để thành lỗi runtime.
- **Cách áp dụng trong v2:** startup validation cho các cặp config liên quan; lộ backend identity (không lộ secret) qua health.

### Lesson: Mỗi storage path phải có consumer
- **Vấn đề trong v1:** bảng write-only (`document_chunks`) tăng migration/drift mà không tạo giá trị.
- **Vì sao quan trọng:** dead storage = nợ kỹ thuật âm thầm.
- **Cách áp dụng trong v2:** mỗi schema mới phải trả lời: ai đọc, khi nào, retention ra sao, recover gì. Kèm retention/prune + index thời gian ngay từ migration đầu.

### Lesson (discovery — giữ lại): Tách trách nhiệm retrieval khỏi access-control
- **Vấn đề trong v1:** nhét permission/filtering vào retrieval layer → sai trách nhiệm.
- **Vì sao quan trọng:** retrieval layer single-tenant không nên biết tổ chức/role.
- **Cách áp dụng trong v2:** retrieval trả raw unit + lineage; access control là việc của caller tầng trên. Có thể *để sẵn field* scope/tags nhưng *không enforce*.

---

## 5. New Repo Decisions

`NEW_REPO_DECISIONS.md` của v1 **cố ý để trống** — repo production chưa chốt quyết định nào. Vì vậy:

### Final Decisions
- (Chưa có) — không có quyết định nào được team v2 ratify trong handoff. **Không** được coi lựa chọn prototype là "final".

### Tentative Decisions (ứng viên — cần team v2 ratify trước khi dùng)
Các invariant được PORTING_GUIDE cho phép *reuse ý tưởng* (vẫn phải đi qua CONSTRAINTS):
- Retrieval unit = đơn vị có nghĩa; embedding unit ≠ retrieval payload.
- Canonical artifact trung gian có địa chỉ ổn định (reprocess rẻ).
- Id deterministic theo địa chỉ nguồn (idempotent reprocess).
- Contract + adapter (business không phụ thuộc SDK).
- Health phản ánh degraded thật; production fail-closed.
- Ghi-đè-trước / prune-sau (atomic-safe replace).
- Embedding-coalescer dùng chung + cache content-hash (giảm cost) — *xem Open Questions về multi-process*.

### Need Confirmation
- Toàn bộ 16 mục `DAY0_CHECKLIST.md` đang ở trạng thái `[ ]` chưa quyết. Mỗi mục phải thành `DECIDED`/`DEFERRED` và được ghi block trong `NEW_REPO_DECISIONS.md` trước commit production đầu.

---

## 6. What NOT To Carry Over From V1

Có bằng chứng trực tiếp trong handoff (README §"Không copy", PORTING_GUIDE §4, MINDSET §4, LESSONS §1):

- **Async nửa vời (offload-to-thread chung).**
  - Không nên carry over: mô hình "edge async + đẩy mọi blocking I/O vào pool chung".
  - Lý do: threadpool saturation; CPU-heavy giẫm serving; bug lifecycle.
  - Cách thay thế trong v2: chọn async-native hoặc sync-có-executor-riêng, tách pool theo loại việc.
- **Fallback im lặng sang mock/in-memory/file ở production.**
  - Không nên carry over: cờ cho-phép-mock default bật.
  - Lý do: phục vụ kết quả sai mà caller tưởng đúng.
  - Cách thay thế trong v2: fail-closed + degraded nhìn thấy được; mock chỉ dev/test.
- **In-memory queue coi như durable.**
  - Lý do: mất job khi restart trước claim.
  - Cách thay thế trong v2: durable queue / bảng pending-job persist / test rediscovery chứng minh.
- **Claim đọc-rồi-ghi không lock + terminal status thiếu claim id.**
  - Lý do: race khi multi-instance.
  - Cách thay thế trong v2: atomic conditional-update + attempt/claim id.
- **Factory/adapter import từ lớp compat/legacy.**
  - Lý do: làm mờ ranh giới "đang chạy thật vs giữ để migrate".
  - Cách thay thế trong v2: import từ vị trí chính tắc; shim chỉ phục vụ test/entrypoint cũ.
- **SDK optional import ở top-level.**
  - Lý do: thiếu dep làm crash cả test suite.
  - Cách thay thế trong v2: lazy import trong khởi tạo/method adapter + skip-nếu-thiếu có marker.
- **Token-chunk làm retrieval unit.**
  - Lý do: xé đơn vị tri thức.
  - Cách thay thế trong v2: chia theo ranh giới nghĩa (heading/section) + guard độ dài + sub-split.
- **Storage/schema write-only; thiếu retention.**
  - Lý do: drift + phình vô hạn + orphan.
  - Cách thay thế trong v2: mỗi storage path khai báo consumer + retention + cleanup.
- **Trigger ingest bằng event bus nặng (broker/topic/DLQ).**
  - Lý do: dữ liệu thật chỉ là file trên object store; event bus tạo coupling khởi động với team khác → code thành dead code.
  - Cách thay thế trong v2: chọn trigger theo *nơi dữ liệu thật nằm* (vd polling), ưu tiên độc lập khởi động — *latency trade-off xem Open Questions*.
- **Cấu trúc flat (gom interface + impl + fallback một file).**
  - Lý do: vi phạm SRP; đổi provider kéo theo sửa business.
  - Cách thay thế trong v2: tách theo capability + chiều phụ thuộc ngay từ đầu.

**Quan trọng — KHÔNG tự động carry over (không có evidence rằng cấu trúc cũ đúng cho v2):**
- folder/file layout cũ của prototype, naming cũ, số lượng contract cũ (~10), thứ tự implement cũ, hay cách chia module cũ. Chỉ giữ *vai trò* (model core / use-case / contract / adapter / composition root / edge), không giữ *cách đặt tên/đường dẫn*.

---

## 7. Recommended V2 Architecture / Workflow

**Hướng chính: Hexagonal tối giản, đơn giản hơn v1.** Handoff support hexagonal như "thứ duy nhất giữ business không cột vào vendor", nhưng cũng cảnh báo boilerplate. Vì vậy v2 giữ *nguyên tắc phân vai*, cắt bớt abstraction không cần.

Phân vai (đặt tên/đường dẫn do team v2 chọn, không copy của v1):

```
edge (HTTP/CLI)  →  use-case (orchestration, no SDK)
                         │ chỉ gọi qua
                         ▼
                 capability contracts  ←  adapters (SDK vendor ở đây)
                         │
                         ▼
                    model core (model + rule, no framework)

   composition root: nơi DUY NHẤT đọc env, chọn adapter, wire
```

Vì sao phù hợp:
- Giữ được invariant cứng (use-case không biết SDK; đổi backend không sửa business; test ở mức contract).
- Đơn giản hơn v1 bằng cách: **không tạo lớp compat ngay từ đầu** (v1 mắc nợ ở đây), **không gom nhiều năng lực vào một interface phình to** (1 contract = 1 năng lực mô tả bằng một câu không có "and"), và **chỉ tạo contract khi thật sự có ≥1 adapter cần thay thế** — nếu chưa cần thay backend, đừng abstract sớm.

Pipeline ingest (theo invariant, không theo file cũ): `nguồn → canonical artifact (địa chỉ ổn định) → chia theo đơn vị nghĩa → caption → embed caption → index full content + lineage`. Mọi bước downstream đọc từ artifact, không đọc lại raw bytes.

Concurrency: chốt MỘT model (§4 Lesson 1) trước khi viết ingest/search; tách executor cho parse/OCR khỏi serving; limit riêng per-stage + per-stage counter trong health.

Alternative (chỉ nêu vì có tension thật trong handoff): nếu v2 xác định **một team, một backend cố định, không có nhu cầu thay provider**, có thể dùng layered đơn giản hơn hexagonal — nhưng phải ghi rõ đánh đổi (mất khả năng thay backend không sửa business) vào `NEW_REPO_DECISIONS.md`.

---

## 8. Day 0 Checklist

Actionable, làm trước commit production đầu (rút gọn từ 16 mục DAY0_CHECKLIST):

- [ ] Tạo repo mới với layout phân vai (edge/use-case/contract/adapter/model core/composition root) — **không** copy cây thư mục prototype.
- [ ] Chốt concurrency model (async-native HOẶC sync-có-executor-riêng) và ghi block vào `NEW_REPO_DECISIONS.md` kèm tên config cho từng concurrency limit.
- [ ] Chạy migration loop rỗng trên DB sạch *và* DB có dữ liệu cũ trước khi thêm bất kỳ schema nghiệp vụ nào; document giới hạn rollback.
- [ ] Đặt default production fail-closed: thiếu credential AI / vector / metadata backend ⇒ fail startup; mock chỉ bật explicit ở dev/test.
- [ ] Thiết kế atomic claim + attempt/claim id (conditional-update, updated_at đổi khi claim, terminal-status guard) trước khi viết repository ingest.
- [ ] Chốt queue recovery policy (rediscovery + max recovery delay) hoặc durable queue; viết test rediscovery.
- [ ] Viết health/readiness endpoint đầu tiên lộ: backend identity, degraded + lý do, queue depth, job dropped/running, scan metrics.
- [ ] Viết security guard I/O (allow-list nguồn, chặn path traversal, check size trước khi đọc body) *trước* code parser; dùng chung sync+async.
- [ ] Thiết lập structured logging gắn correlation id (document id / request id / stage / duration / backend name) từ commit đầu.
- [ ] Quy ước lazy import SDK trong adapter + skip-nếu-thiếu có marker; phân lớp dep (unit-bắt-buộc / integration-optional / full-env).
- [ ] Viết contract test dùng chung chạy trên cả in-memory lẫn backend thật cho claim/prune/dimension.
- [ ] Encode dimension vào định danh index + viết runbook reindex/rollback (đổi dimension = migration).
- [ ] Viết startup config-compatibility validation (provider+baseURL+model, model+dimension+index, backend+credential) + test config sai phổ biến.
- [ ] Viết test đầu tiên cho cancellation/shutdown của task nền (drain trước khi đóng tài nguyên dùng chung).
- [ ] Định nghĩa eval gate: golden queries + expected source lineage + tiêu chí recall/precision/no-answer + latency p50/p95 target; chỉ định owner.
- [ ] Lập bảng "loại dữ liệu → owner → retention → cleanup" + chốt trần chi phí cho AI/OCR/embedding + metric cost theo stage.
- [ ] Pin image bằng SHA/digest + viết bước verify-after-deploy (image thật + health + migration state).

---

## 9. AI Agent Operating Rules

### Agent được làm gì
- Đọc `docs/handoff/` trước khi đề xuất hoặc viết code.
- Đề xuất structure mới đơn giản hơn v1 dựa trên *vai trò*, không trên layout cũ.
- Implement một mục Day 0 sau khi mục đó đã `DECIDED`/`DEFERRED` và ghi vào `NEW_REPO_DECISIONS.md`.
- Viết test (general + edge: input rỗng/null, dependency lỗi, boundary, race/idempotency) cho mỗi thay đổi.

### Agent không được làm gì
- Không copy code/folder/naming/workflow prototype chỉ vì "nó đang chạy".
- Không import SDK vào use-case layer hoặc model core; không tạo alias/compat mới.
- Không thêm offload-to-thread mới trong use-case layer; không spawn fire-and-forget task không track.
- Không bật fallback mock/in-memory ở production default.
- Không tạo storage path/bảng/index mới khi chưa biết ai đọc + retention.
- Không đổi provider/model/dimension như config rời rạc thiếu validation/migration.
- Không merge thay đổi retrieval chỉ vì "thử tay thấy đúng".

### Khi nào phải hỏi lại user
- Một mục Day 0 chưa được chốt nhưng cần dùng để implement tiếp.
- Phải dùng tạm một item trong "What NOT To Carry Over" (cần ghi rõ vì sao tạm, rủi ro, khi nào thay).
- Stack/backend cụ thể chưa được chỉ định (handoff cố ý trung tính về stack).
- Phát hiện mâu thuẫn giữa handoff và yêu cầu hiện tại.

### Khi nào phải dừng lại và report
- Một thay đổi vi phạm chiều phụ thuộc hoặc một constraint cứng ở §3.
- Thay đổi chạm Docker/K8s/CI/migration/secret nhưng chưa có deploy verification.
- Một quyết định kiến trúc mới phát sinh chưa có block trong `NEW_REPO_DECISIONS.md`.
- Phát hiện storage write-only / config mismatch / claim race / threadpool saturation.

### Cách change code an toàn
- Mỗi PR đi qua Pre-Commit Checklist (CONSTRAINTS §4): chạy được với toàn bộ mock? không SDK trong use-case? đúng chiều phụ thuộc? health đúng degraded? idempotent reprocess? guard I/O đủ?
- Thay đổi nhỏ, một mục tiêu; không trộn refactor với feature.

### Cách port code an toàn
- Port theo *invariant/ý tưởng* (PORTING_GUIDE §3), không port nguyên file.
- Mỗi đoạn port phải đi qua CONSTRAINTS trước khi nhận vào runtime path.
- Trước khi reuse bất kỳ thứ gì từ v1, tự hỏi: (1) nó giải quyết vấn đề gì ở v2? (2) còn cần không? (3) có cách đơn giản hơn? (4) có mang theo debt/rủi ro v1 không? Không chắc ⇒ đưa vào Open Questions, không copy.

### Cách refactor an toàn
- Có contract test xanh trước khi refactor; giữ contract ổn định.
- Không để lại shim trên runtime path; nếu tạo shim tạm, ghi điều kiện xoá vào `NEW_REPO_DECISIONS.md`.

### Cách commit/report tiến độ
- Commit message nêu rõ mục Day 0 / constraint liên quan.
- Khi chốt/đổi quyết định kiến trúc ⇒ cập nhật `NEW_REPO_DECISIONS.md` trong cùng PR.
- Report nêu: đã làm gì, test nào chạy + kết quả thật (fail thì nói fail kèm output), bước nào skip, mục Day 0 nào còn `[ ]`.

---

## 10. Risk Register For V2

| Risk | Cause | Early Warning Sign | Prevention | Recovery Plan |
|---|---|---|---|---|
| Production phục vụ kết quả sai mà caller tưởng đúng | Fallback im lặng sang mock/in-memory; cờ mock default bật | Health vẫn ok dù backend chính lỗi; degraded_reason không rỗng nhưng vẫn nhận traffic | Fail-closed default; health unhealthy khi degraded; strict-mode guard ở startup | Tắt traffic; bật fail-closed; reindex/recompute phần phục vụ từ backend sai |
| Job cũ ghi đè trạng thái job mới | Claim đọc-rồi-ghi không lock, thiếu claim id | Trạng thái document "nhảy ngược"; status không khớp run thật khi >1 instance | Atomic conditional-update + attempt/claim id + guard số dòng ảnh hưởng | Reconcile theo claim id; reprocess document bị lệch (id deterministic ⇒ idempotent) |
| Mất job khi restart | In-memory queue, chưa claim | Job biến mất sau redeploy; backlog không khớp nguồn | Durable queue / pending-job persist / rediscovery test | Re-scan nguồn để rediscover job chưa-claim |
| Threadpool saturation, serving timeout | Async nửa vời, một pool chung | Search latency tăng vọt khi ingest nặng | Tách executor parse/OCR khỏi serving; per-stage limit + counter | Giảm ingest concurrency; tách pool; chuyển sang async-native |
| Deploy xanh nhưng chạy code cũ | Image không pin / tag mutable | Bug đã fix vẫn tái xuất; digest pod ≠ artifact mới | Pin SHA/digest; verify image+health sau rollout | Re-pin digest đúng; redeploy; verify pod image |
| Config mismatch lộ ở runtime | Provider/baseURL/model/dimension không validate cùng nhau | 401, dimension mismatch ở request đầu | Startup compatibility validation + test config sai | Sửa config; chặn traffic tới khi validate pass |
| Storage phình vô hạn / orphan | Thiếu retention; rename nguồn để lại metadata | job-log/index tăng tuyến tính; record trỏ nguồn không tồn tại | Bảng retention + prune + reconcile orphan ngay từ migration đầu | Chạy prune/reconcile job; thêm policy còn thiếu |
| Chi phí AI/OCR vượt kiểm soát | Không trần chi phí; OCR tài liệu visual đắt | Cost/latency tăng đột biến ở document scan | Trần chi phí/lần xử lý + cảnh báo + cache content-hash + policy từ chối/hoãn | Bật trần + cache; hoãn/giảm cấp document quá đắt |
| Retrieval quality giảm âm thầm | Đổi parser/caption/model/splitter/index không đo lại | No-answer behavior đổi; nhầm source lineage | Eval gate (golden queries + expected lineage) chặn merge | Revert thay đổi; chạy lại eval; chốt nguyên nhân |
| Đơn vị nghĩa quá dài → consumer overflow | Tài liệu thiếu cấu trúc | Caller báo context vượt giới hạn | Guard độ dài + sub-split theo ranh giới nhỏ hơn, giữ lineage | Re-split tài liệu vượt ngưỡng; điều chỉnh threshold |

---

## 11. Open Questions

- **Stack/backend cụ thể của v2 là gì?**
  - Vì sao cần hỏi: handoff cố ý trung tính về stack; không có quyết định ratified.
  - Nếu không hỏi: agent sẽ tự giả định stack v1 → vi phạm nguyên tắc "V1 không phải template".
- **Async-native hay sync-có-executor-riêng?**
  - Vì sao cần hỏi: handoff để ngỏ (Unresolved); quyết định định hình toàn bộ I/O layer.
  - Nếu không hỏi: dễ lặp lại async nửa vời của v1.
- **V2 có chạy multi-instance (scale ngang) ngay không?**
  - Vì sao cần hỏi: claim race / terminal-status chỉ nguy hiểm khi >1 instance; quyết định mức đầu tư cho atomic claim + durable queue.
  - Nếu không hỏi: hoặc over-engineer cho single-instance, hoặc thiếu an toàn khi scale.
- **Trigger ingest: polling hay event-driven?**
  - Vì sao cần hỏi: tension thật trong handoff (polling độc lập nhưng latency = chu kỳ scan; event nhanh hơn nhưng thêm coupling hạ tầng). Có SLO "searchable trong X phút" không?
  - Nếu không hỏi: chọn sai trigger → hoặc latency không đạt, hoặc coupling khởi động như v1.
- **Cache embedding: in-memory hay external?**
  - Vì sao cần hỏi: coalescer + cache content-hash được giữ lại, nhưng cache in-memory không sống qua restart / không chia sẻ cross-process.
  - Nếu không hỏi: cache mất tác dụng khi chuyển multi-process, cost tăng lại.
- **Model core thuần hay chấp nhận một framework validation?**
  - Vì sao cần hỏi: handoff để ngỏ; chỉ cần thuần nếu model core phải dùng *ngoài* service (portability thành yêu cầu cứng).
  - Nếu không hỏi: hoặc mất tốc độ dev sớm, hoặc cột core vào framework khi sau này cần portable.
- **Embed caption-only hay hybrid (caption + nội dung)?**
  - Vì sao cần hỏi: handoff để ngỏ; caption-only có thể mất recall cho truy vấn cần khớp chính xác thuật ngữ/số.
  - Nếu không hỏi: thiếu rerank/hybrid cho corpus nặng thuật ngữ → recall kém.
- **Có môi trường deploy (K8s) ở v2 không?**
  - Vì sao cần hỏi: quyết định mức cần của deploy verification / image pinning.
  - Nếu không hỏi: hoặc bỏ verification cần thiết, hoặc thêm overhead không cần.

---

## 12. Final Transfer Note

Gửi người/agent tiếp theo: **học từ v1 nhưng đừng để v1 khoá tay bạn.** Các file handoff cho bạn thấy chính xác cái gì đã đau và *vì sao* — đó là vàng. Nhưng cây thư mục, tên class, thứ tự implement của prototype chỉ là một lần hiện thực, không phải bản thiết kế đúng. Bắt đầu lại sạch: structure đơn giản nhất giữ được các invariant cứng, ít abstraction, dễ test, dễ port từng phần. Trước khi reuse bất cứ thứ gì từ v1, hỏi nó còn cần không và có cách đơn giản hơn không — không chắc thì đưa vào Open Questions chứ đừng copy. Chốt quyết định Day 0 *trước* khi code, ghi vào `NEW_REPO_DECISIONS.md`, verify từng bước (test thật, deploy thật, eval thật), và không bao giờ build theo một assumption mơ hồ.

---

## 13. Suggested Next Prompts

### Prompt 1: Setup repo mới
> Dựa trên `V2_HANDOFF.md`, hãy đề xuất layout repo mới cho v2 theo *vai trò* (edge / use-case / contract / adapter / model core / composition root) — KHÔNG copy cây thư mục prototype. Với mỗi thư mục, giải thích ngắn nó giữ invariant nào. Sau đó liệt kê các mục Day 0 cần chốt trước commit đầu, đề xuất default cho từng mục, và tạo skeleton `NEW_REPO_DECISIONS.md` với block trống cho từng quyết định. Chỉ rõ phần nào cần tôi confirm trước khi bạn viết code.

### Prompt 2: Port từng phần từ prototype cũ
> Tôi muốn port `<tên capability, vd: canonical artifact / id deterministic / coalescer>` từ prototype sang v2. Hãy: (1) mô tả invariant/ý tưởng cần giữ theo `V2_HANDOFF.md`, (2) chỉ ra cái gì của bản v1 KHÔNG nên mang theo và vì sao, (3) đề xuất bản v2 đơn giản hơn đi qua được CONSTRAINTS §3, (4) viết contract test dùng chung chạy trên cả in-memory lẫn backend thật. Trước khi viết code, trả lời 4 câu reuse-check (giải quyết vấn đề gì ở v2 / còn cần không / có cách đơn giản hơn / có mang debt v1 không). Không chắc thì đưa vào Open Questions.

### Prompt 3: Review architecture trước khi code
> Trước khi tôi implement sâu, hãy review architecture/workflow đề xuất cho v2 dựa trên `V2_HANDOFF.md`. Kiểm tra: chiều phụ thuộc một chiều có giữ không, có SDK rò vào use-case/model core không, contract có bị phình to (có "and") không, concurrency model đã chốt chưa, fallback có fail-closed không, health có phản ánh degraded không, có storage write-only không, eval gate + deploy verification + config validation đã có chưa. Liệt kê vi phạm constraint cứng (nếu có) và các quyết định Day 0 còn thiếu trước khi cho phép code production.
