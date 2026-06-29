# Tuần 1 (29/05 → 04/06) — Dựng nền rag-worker

Học sâu theo commit, **timeline**. Mỗi commit: làm gì / vì sao / vì sao code vậy / bug & gốc rễ / học.
Đọc từ diff thật (`git show <hash>`). Tuần này = mang prototype về, dựng kiến trúc hexagonal, và
một **bug merge xóa file âm thầm** nhớ đời.

---

## 01/06 — Khởi tạo repo v2 từ prototype

### `ccae2735` transfer from prototype
- **Đã làm:** Bootstrap `docs/handoff/` (7 file, ~1041 dòng, **chỉ docs, không code**): CONSTRAINTS, DAY0_CHECKLIST, LESSONS, MINDSET, NEW_REPO_DECISIONS (template), PORTING_GUIDE, README.
- **Vì sao:** Khởi tạo repo v2 — chuyển *tri thức/ràng buộc/checklist* sang repo mới thay vì bê code thẳng.
- **Vì sao code vậy:** Tách "handoff bundle" làm nguồn học (authority = handoff, không phải prototype) trước khi viết dòng code nào.
- **Học:** Port prototype = port **quyết định + bài học trước, code sau**.

## 02/06 — Lớp quyết định kiến trúc + nền WHAT/WHY

### `5bf690b6` add V2 design decisions (decide/)
- **Đã làm:** `docs/decide/` (18 file, ~1957 dòng): `concise.md` (master), `NEW_REPO_DECISIONS.md` (D1–D8 PROPOSED), diagram mermaid (ingestion/search/scaling/overview), `technique/*` (parser, embedding gateway, execution-fallback…).
- **Vì sao:** Distill handoff thô → quyết định kiến trúc *actionable* (trigger event+scanner, parser stateless, embedding gateway, pluggable execution+fallback, content_ref, backend abstraction).
- **Vì sao code vậy:** Mỗi quyết định để `PROPOSED` (chưa RATIFIED); convention `★` = phải chốt, non-★ = đã grounded → tránh prototype bị coi là chân lý. Diagram (topology) tách technique (cách làm).
- **Học:** Quyết định kiến trúc phải có **chủ / ngày / trade-off / điều kiện review**; ghi PROPOSED→RATIFIED tường minh.

### `11658bec` provide docs · `9a92738e` domain docs · `e35048aa` nền WHAT/WHY + 5 tầng
- **Đã làm:** `domain-model.md` (ubiquitous language, bounded context, rule kèm lý do), `design-flow.md` (chuỗi 5 tầng REQ→rule→ARCH→TECH), `architecture-mapping.md` (ma trận rule→component). `e35048aa` tái cấu trúc `docs/` phẳng → 6 thư mục theo tầng bằng **`git mv`** (giữ blame).
- **Vì sao:** Docs phẳng không truy vết được nghiệp vụ→kỹ thuật; cần mỗi quyết định kỹ thuật neo về 1 rule/lý do.
- **Học:** `git mv` thay vì xóa+tạo để giữ lịch sử; **ma trận rule→component chủ động lộ gap** kiến trúc.

### `9aeeea3a` lesson notes
- Docs thuần (vectordatabase, websocket-fastapi — có bản HTML). Tài liệu tham chiếu nội bộ, không đụng code.

## 03/06 — Hexagonal: AI gateway + vectorstore pluggable

### `9eb3a585` module-hóa core_engine + AI gateway singleton
- **Đã làm:** Tái cấu trúc `haystack_interface/` phẳng → module severable (`ai/ embedding/ caption/ rerank/ chunking/ vectorstore/ access/`). Thêm `ai/` = **AI gateway** — điểm vào DUY NHẤT cho mọi outbound AI call: `AIProvider` interface + singleton, `OpenAIProvider` + `OfflineProvider`, retry/backoff/jitter đồng nhất, validate fail-fast. `engine.py` chỉ phụ thuộc *port*; `factory.py` = composition root đổi offline↔OpenAI một chỗ. Gỡ vendored `haystack/` khỏi git.
- **Vì sao:** Layout phẳng trộn AI call rải rác → khó test offline, khó swap provider, retry không đồng nhất.
- **Vì sao code vậy:** Hexagonal — engine phụ thuộc interface chứ không phụ thuộc SDK; gom call AI qua 1 gateway để áp 1 reliability policy + swap provider 1 chỗ; `OfflineProvider` cho selftest PASS không cần mạng.
- **Học:** **Mọi outbound AI call qua 1 gateway/port duy nhất**; retry + provider-swap là cross-cutting → đặt ở composition root. (Đây là tiền thân tư duy sau này đẻ ra ai-router.)

### `ec171b8d` vectorstore pluggable
- **Đã làm:** Bung `vectorstore/` từ 1 file `inmemory.py` → provider pluggable: `provider.py` (interface) + `registry.py` + `store.py` + 3 backend (chromadb / milvus / qdrant), mỗi cái `base/inprocess/remote`. Thêm `tests/_contract.py` (**contract test dùng chung**).
- **Vì sao:** In-memory không scale; cần chọn Qdrant mà không khóa chết core vào 1 vendor.
- **Vì sao code vậy:** Registry + interface + **1 contract test cho mọi backend** → thêm backend chỉ cần implement interface + pass contract.
- **Học:** Contract test 1 nguồn cho nhiều backend = giữ pluggability không vỡ khi swap vendor.

## 03–04/06 — Hạ tầng runtime: migration, logging, health, contract

> (Loạt commit `rag-service:` — đọc thêm `git show` để xem chi tiết hàm)
- **alembic migration thay `create_all`** ad-hoc + port `update_chunk_count`: schema versioned thay vì tạo bảng tùy hứng → deploy/rollback an toàn.
- **structured JSON logging** thay `print()`: log máy đọc được cho observability sau này.
- **fail-closed startup health**: thiếu dependency thì service KHÔNG lên (an toàn hơn lên rồi lỗi runtime).
- **enforce search contract**: khóa shape kết quả search → caller không vỡ ngầm.
- **fix offline rerank prompt/parser drift**: prompt sinh và parser đọc bị lệch → chuẩn hóa.
- **Học:** Nền tảng "an toàn mặc định" (fail-closed, migration versioned, contract) đặt từ tuần 1 trả nợ cực lớn về sau.

## 04/06 — Rename + BUG MERGE XÓA NGẦM (nhớ đời)

### `84625d3d` rename src/rag-service → src/rag-worker
- **Đã làm:** Rename thuần thư mục (0 byte nội dung đổi) để khớp tên service của `main` (rag-worker = ingestion/retrieval qua NATS, no HTTP port).
- **Vì sao code vậy:** Giữ implementation đã test nguyên vẹn, chỉ đổi path main đã đặt → khỏi viết lại.

### `92227c23` Restore 35 files silently dropped by the merge ⚠️ **(commit sửa-lại)**
- **Đã làm:** Khôi phục 36 file vào `src/rag-worker` từ commit nguyendev đã-biết-tốt (`0239f40`): các `__init__.py` rỗng, `embedding_service.py` (ABC port), toàn bộ `docs/decide` + `handoff`. Sau khôi phục: **73 test passed** lại.
- **Bug & gốc rễ:** Merge `origin/main` (`6dabb65e`) gặp **modify/delete auto-resolve âm thầm**: file mà nguyendev KHÔNG đổi từ merge-base nhưng main đã XÓA → Git tự lấy phía "delete", **không báo conflict**. Mất hàng loạt `__init__.py` (gãy import package) + port. Gốc: 3-way merge coi "một bên xóa, một bên không sửa" = "đồng ý xóa".
- **Học:** Merge từ nhánh "thiếu file" rất nguy. **Sau merge lớn phải kiểm `__init__.py`/import + chạy full test — đừng tin 'merge sạch không conflict'.** Khôi phục thì lấy từ commit biết-tốt + dùng test làm hệ quy chiếu.

### `94c1073e` drop main's README · `d111eff3` gitignore haystack path *(2 commit dọn dư sau rename)*
- Dọn README skeleton thừa của main (giữ bất biến "pure rename") + sửa path ignore `haystack/` (~9k file clone) sau đổi tên. → **Bất biến tường minh ("pure rename") thì file lạ duy nhất cũng phải dọn.**

### `a516819e` lấy lại bản docs gốc từ main ⚠️ **(revert một phần `e35048aa`)**
- **Đã làm:** `git mv` ngược docs 6-tầng về phẳng, đổi tên lại theo main (solution-architecture→`SA_RAG_Chatbot_Final.md`…).
- **Vì sao:** `main` (nguồn sự thật team) vẫn layout phẳng; cấu trúc 5-tầng đã phân kỳ.
- **Học:** **Đừng tái cấu trúc lớn khi nhánh chính chưa đồng thuận** → tạo 2 nguồn docs lệch nhau, phải hoàn tác. (Trớ trêu: 3 tuần sau lại refactor docs — nhưng lần đó có đồng thuận + verify từ code.)

## 04–05/06 — NATS transport, parser nguồn, đưa vào develop

### `1463c430` Add rag-worker service to develop
- **Đã làm:** **1 commit phẳng additive** trên đỉnh develop — chỉ thêm `src/rag-worker`, không đụng file khác.
- **Vì sao code vậy:** Tránh lặp sự cố merge-âm-thầm; develop chỉ thấy đúng thứ cần, dễ review/revert.
- **Học:** Nhập service ổn định vào nhánh chính → **"single clean additive commit" an toàn hơn merge** (cô lập, không tác dụng phụ liên-file của 3-way merge).

### NATS `doc.ingest` transport + durable subscription + S3/GCS parser
- **doc.ingest transport + doc.delete consumer**: ingest bất đồng bộ qua message queue thay vì gọi đồng bộ → chịu burst, retry.
- **durable subscription + dedup redelivery + publish failed status**: NATS phải durable mới không mất message khi worker restart; redelivery phải dedup; lỗi phải publish status để caller biết.
- **S3/GCS source parser + botocore <1.36 checksum**: nguồn dùng giao thức S3-interop (prod = GCP); botocore <1.36 đổi checksum kwargs → phải tương thích.
- **Python 3.13 wheel pin**: build vỡ vì thiếu wheel cho 3.13 → pin version có wheel.
- **tách mcp-service search-only** + e2e Docker CI: search tách khỏi ingest.
- **Học:** Message queue cho ingest = chịu tải + bền; nhưng "durable + dedup + failed-status" là 3 thứ BẮT BUỘC, thiếu 1 là mất/kẹt message.

---
### Đọng lại tuần 1
- Kiến trúc đặt nền đúng: **hexagonal (port/adapter), AI gateway 1 cửa, vectorstore pluggable, contract test, fail-closed, migration versioned** — tất cả trả nợ về sau.
- Bài học đắt nhất: **merge có thể xóa file mà không conflict** → luôn full-test sau merge.
- Bài học quy trình: **đừng tái cấu trúc khi nhánh chính chưa đồng thuận**.
