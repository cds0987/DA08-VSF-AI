# MINDSET — Tư duy thiết kế để build lại từ đầu

> **Mục đích:** File này không mô tả code. Nó capture lại *tại sao* mọi quyết định kiến trúc có ý nghĩa, để người (hoặc AI agent) build lại hệ thống — **trên stack hay cấu trúc thư mục bất kỳ** — ra được quyết định giống tác giả, không phải copy code.
>
> **Cách đọc:** Mỗi mục nêu **nguyên tắc tổng quát** trước. Chỗ nào có `Trong prototype:` là *minh hoạ một lần hiện thực* — tham khảo, không phải ràng buộc. Repo mới có thể đặt tên/cấu trúc khác; giữ *nguyên tắc*, bỏ *cách đặt tên*.
>
> Đọc sau [PORTING_GUIDE.md](./PORTING_GUIDE.md); trước [DAY0_CHECKLIST.md](./DAY0_CHECKLIST.md), [CONSTRAINTS.md](./CONSTRAINTS.md), [LESSONS.md](./LESSONS.md).

---

## Vocabulary trung tính (dùng xuyên suốt bundle)

Để không cột vào tên thư mục cụ thể, bundle này gọi các thành phần theo **vai trò**:

- **Model core** — model + business rule, không phụ thuộc framework/SDK.
- **Use-case layer** — orchestration của một luồng nghiệp vụ; không chứa logic SDK.
- **Capability contract** — interface nhỏ mô tả một năng lực (port/protocol/interface).
- **Adapter** — hiện thực một contract bằng SDK/vendor cụ thể.
- **Composition root** — nơi *duy nhất* chọn adapter theo environment và wire mọi thứ.
- **Edge layer** — nơi nhận request ngoài vào (HTTP/CLI/queue), validate và map response.

Khái niệm *nghiệp vụ* (document, section, caption, canonical artifact, document id) là bài toán — giữ nguyên ý nghĩa kể cả khi đổi stack.

---

## Section 1: Core Problem Statement

Bài toán không phải "build RAG pipeline" mà là: **biến một kho tài liệu hỗn tạp (PDF scan, office docs, HTML, ảnh) thành một lớp retrieval mà tầng tiêu thụ phía trên có thể tin tưởng làm grounding — và luôn truy ngược được về nguồn gốc.** Insight cốt lõi: người dùng cuối cần *một đơn vị tri thức hoàn chỉnh* chứ không phải một mảnh văn bản bị cắt giữa câu; do đó đơn vị retrieve phải là đơn vị có *nghĩa* (một section theo cấu trúc tài liệu), không phải đơn vị *kỹ thuật* (một khối token cố định). Insight thứ hai: thứ đáng để embed/search không phải raw text — mà là *ý nghĩa nén* của đơn vị đó, vì nó khử vocabulary mismatch giữa câu hỏi tự nhiên và văn phong tài liệu. Insight thứ ba, phân biệt hệ này với keyword search: keyword chỉ khớp *từ*; hệ này khớp *ý định* (semantic) rồi trả về context đủ rộng để tầng trên trả lời mà không bịa. Cuối cùng — và đây là thứ định hình toàn bộ failure policy — rủi ro lớn nhất của một hệ retrieval không phải "chết", mà là **"vẫn sống nhưng trả kết quả sai mà caller tưởng đúng"**; nên mọi degraded/fallback phải nhìn thấy được, không được im lặng.

---

## Section 2: Design Principles

### Đơn vị retrieve là đơn vị có nghĩa, không phải đơn vị kỹ thuật
→ Vì vậy ta làm: chia tài liệu theo *cấu trúc nghĩa* mà chính tác giả tài liệu tạo ra (heading/section), giữ thứ tự và đường dẫn phân cấp; trả về nguyên đơn vị đó.
→ Vì vậy ta KHÔNG làm: cắt theo độ dài token với sliding-window overlap; coi token-count là ranh giới.
→ Trong prototype: split markdown theo heading thành "section" có `heading_path` + `section_order` + full content.

### Embedding unit ≠ retrieval payload: embed ý nghĩa nén, trả về nội dung đầy đủ
→ Vì vậy ta làm: sinh một tóm tắt ngắn (caption) biểu diễn ý nghĩa đơn vị, embed *caption đó*; nhưng index và trả về *full content*. Vector và payload là hai thứ khác nhau.
→ Vì vậy ta KHÔNG làm: embed raw text dài; trả tóm tắt thay cho nội dung.
→ Trong prototype: vector = embedding của caption; payload giữ cả caption lẫn full section content.

### Mọi đầu vào hội tụ về một canonical artifact trước khi xử lý downstream
→ Vì vậy ta làm: chuẩn hoá mọi format về *một dạng trung gian thống nhất*, lưu thành artifact có địa chỉ ổn định, rồi downstream chỉ làm việc trên artifact đó — không đụng lại raw bytes.
→ Vì vậy ta KHÔNG làm: cho mỗi parser trả shape khác nhau; cho các bước sau đọc lại file gốc.
→ Trong prototype: parse mọi format → một Markdown artifact (`{prefix}/{document_id}`), split/caption/embed đều đọc từ markdown.

### Use-case layer chỉ biết contract, không bao giờ biết SDK
→ Vì vậy ta làm: use case nhận dependency qua capability contract; chỉ adapter mới import SDK vendor.
→ Vì vậy ta KHÔNG làm: import SDK vào use-case layer hay model core; cho edge layer tự dựng client.
→ Trong prototype: use case ingest nhận ~10 contract (reader/parser/store/splitter/captioner/embedder/index/repo...); use case search chỉ nhận contract embed + contract index.

### Một composition root duy nhất chọn implementation theo environment
→ Vì vậy ta làm: một nơi *duy nhất* đọc config để chọn adapter (backend A vs B, thật vs mock) và wire tất cả.
→ Vì vậy ta KHÔNG làm: rải `if config == "X"` khắp code; cho mỗi module tự quyết fallback riêng.
→ Trong prototype: một hàm build container đọc env, chọn vector/metadata/AI backend, khởi tạo mọi adapter + use case.

### Contract nhỏ theo capability (Interface Segregation), không một interface phình to
→ Vì vậy ta làm: tách năng lực thành các contract riêng dù chung một backend; caller chỉ nhận đúng contract nó cần.
→ Vì vậy ta KHÔNG làm: một interface khổng lồ ép module A phải biết năng lực của module B.
→ Trong prototype: repository tách thành 3 contract riêng (đọc/ghi document, claim ingest, ghi job log) dù cùng một store backing.

### Degraded phải nhìn thấy được, không im lặng
→ Vì vậy ta làm: mọi fallback ghi lại lý do rõ ràng; health/status surface báo "unhealthy" (mã lỗi rõ) khi degraded, không báo "ok".
→ Vì vậy ta KHÔNG làm: fallback sang mock/in-memory/file rồi báo ok như bình thường.
→ Trong prototype: fallback append vào `degraded_reasons`; health endpoint trả 503 khi degraded thay vì 200.

### Delivery cũng là một phần của hệ thống, không phải việc phụ bên ngoài
→ Vì vậy ta làm: mỗi lần deploy phải chứng minh được *phiên bản mới thật sự đang chạy*, không chỉ CI báo xanh hoặc rollout status thành công.
→ Vì vậy ta KHÔNG làm: dùng tag mutable kiểu `latest`, dựa vào apply manifest mà không kiểm tra image digest/tag trên pod, hoặc xem "kubectl apply không lỗi" là bằng chứng production đã đổi code.
→ Trong prototype: từng có deploy thành công nhưng pod vẫn chạy code cũ do image pin trong kustomize không match; lỗi này tốn thời gian vì mọi tín hiệu CI đều trông hợp lệ.

### Config runtime là contract, không phải ghi chú vận hành
→ Vì vậy ta làm: mọi cặp config có quan hệ ngữ nghĩa (provider/base URL/model name, embedding model/dimension/index, backend mode/credential) phải được validate sớm và lộ rõ qua health/status.
→ Vì vậy ta KHÔNG làm: cho config sai chạy đến runtime rồi fail bằng lỗi 401, dimension mismatch, hoặc silently fallback.
→ Trong prototype: từng sai base URL/model format khi đổi provider, và từng mismatch embedding dimension giữa mock/provider/index.

### Tính đúng dữ liệu trước, throughput sau
→ Vì vậy ta làm: ưu tiên các bất biến consistency (claim một chủ, ghi đè idempotent, không bỏ trạng thái nửa vời) trước khi tối ưu tốc độ.
→ Vì vậy ta KHÔNG làm: tăng song song khi chưa đảm bảo hai job không giẫm chân nhau.
→ **[INFERRED]** Trong prototype: thứ tự ưu tiên migration đặt metadata/consistency trước storage/vector throughput.

---

## Section 3: Key Decisions Log

### Hexagonal (contract + adapter) thay vì layered/flat
**Vấn đề:** Tiền thân là code flat nơi store/provider/fallback nhồi chung một file; cần nhiều người làm song song mà không đụng nhau, và đổi backend không vỡ business.
**Options:**
- A: Giữ flat + thêm chức năng — bỏ, mỗi lần đổi provider kéo theo sửa business, merge conflict.
- B: Layered (controller→service→repository) — bỏ, layered vẫn cho service phụ thuộc trực tiếp implementation.
- C (đã chọn): Hexagonal — phụ thuộc một chiều `model core ← use case → contract ← adapter`, một composition root. Ép được "đổi backend không sửa use case" và test mock ở mức contract.
**Trade-off:** Nhiều boilerplate (contract + adapter + wiring); thừa với hệ rất nhỏ. Model core vẫn có thể dính một framework validation.
**Khi nào xem lại:** Khi hệ thu còn một team một backend cố định, không còn nhu cầu thay provider.

### Đơn vị-nghĩa thay vì đơn vị-kỹ-thuật cho retrieval
**Vấn đề:** Cắt theo token cố định làm một đơn vị tri thức (policy/quy trình) bị xé thành nhiều mảnh; search trả mảnh thiếu đầu thiếu đuôi; tài liệu dài sinh hàng nghìn mảnh khớp theo token-overlap chứ không theo nghĩa.
**Options:**
- A: Khối token + overlap — bỏ, đơn vị kỹ thuật ≠ đơn vị nghĩa.
- B: Cắt theo câu/đoạn cố định — bỏ, vẫn cắt ngang ý.
- C (đã chọn): Cắt theo ranh giới nghĩa do cấu trúc tài liệu tạo (heading) + fallback cho tài liệu không cấu trúc.
**Trade-off:** Đơn vị có thể rất dài nếu tài liệu thiếu cấu trúc → caller nhận context vượt giới hạn mà không cảnh báo (cần guard độ dài — xem [DAY0_CHECKLIST.md](./DAY0_CHECKLIST.md)).
**Khi nào xem lại:** Khi corpus chủ yếu là tài liệu phẳng không cấu trúc, hoặc khi caller báo overflow thường xuyên.

### Một embedding-coalescer dùng chung thay vì embed per-request
**Vấn đề:** Mỗi job embed độc lập → N job đồng thời = N call nhỏ rời rạc; reprocess cùng nội dung gọi lại embed dù nội dung không đổi.
**Options:**
- A: Embed per-job — bỏ, lãng phí, không coalesce.
- B: Hàng đợi chung không cache — bỏ một nửa, vẫn embed lại nội dung trùng.
- C (đã chọn): Một coalescer dùng chung gom request cross-job thành batch lớn, flush theo *size* HOẶC *time-window*, + cache theo content-hash bỏ qua nội dung đã embed.
**Trade-off:** Là shared mutable state trên đường async → phải xử lý cẩn thận lifecycle của future, cancellation, và drain lúc shutdown (xem [LESSONS.md](./LESSONS.md)). Cache in-memory không sống qua restart và không chia sẻ cross-process.
**Khi nào xem lại:** Khi chuyển multi-process (cache in-memory mất tác dụng → cân nhắc cache ngoài), hoặc nếu provider đã tự batch tốt.

### Tóm tắt-nén (caption) làm embedding unit thay vì raw content
**Vấn đề:** Câu hỏi tự nhiên dùng từ vựng khác văn phong tài liệu → embed raw text gây vocabulary mismatch → recall kém.
**Options:**
- A: Embed raw content — bỏ, mismatch ngữ vựng, vector loãng theo độ dài.
- B: Embed cả tóm tắt lẫn nội dung (hybrid) — để ngỏ (Section 5).
- C (đã chọn): Embed tóm tắt, index nội dung. Giải quyết mismatch *tại indexing time*, vector gọn, semantic rõ.
**Trade-off:** Toàn bộ retrieval quality phụ thuộc chất lượng tóm tắt — tóm tắt sai ý thì search lệch dù hạ tầng đúng. Thêm một AI call/đơn vị vào critical path.
**Khi nào xem lại:** Khi đo được tóm tắt làm mất recall cho truy vấn cần khớp chính xác thuật ngữ/số → cần hybrid hoặc rerank bằng nội dung.

### Async-native vs "async nửa vời" (offload blocking sang thread)
**Vấn đề:** Cần concurrency (tóm tắt song song, scanner không block, nhiều job đồng thời) nhưng SDK gốc thường blocking.
**Options:**
- A: Thread pool workers — bỏ, mỗi thread chờ network tốn RAM + scheduling; các bước tuần tự chậm.
- B: Async-native (client async cho mọi I/O) — đúng đích nhưng effort lớn + một số client async là wrapper cộng đồng rủi ro.
- C (đã chọn tạm thời): Event loop + offload mọi blocking I/O sang threadpool mặc định; chỉ một số bước (như tóm tắt) song song thật bằng gather + semaphore.
**Trade-off:** "Async nửa vời" — mọi I/O vẫn dùng *chung một* threadpool mặc định; bước CPU nặng (parse) và đường serving (search) giẫm chân nhau. Đây là nợ kỹ thuật được ghi nhận rõ.
**Khi nào xem lại:** Quyết định dứt khoát từ đầu ở repo mới (xem [DAY0_CHECKLIST.md](./DAY0_CHECKLIST.md) D1): async-native hoặc sync-có-executor-riêng, **không nửa vời**.

### Document id deterministic theo địa chỉ nguồn, không content-hash, không ngẫu nhiên
**Vấn đề:** Cần idempotent reprocess: nạp lại cùng nguồn phải ghi đè đúng record cũ, không tạo duplicate.
**Options:**
- A: ID ngẫu nhiên (UUID) — bỏ, reprocess tạo bản mới, duplicate.
- B: Hash theo nội dung — bỏ, sửa một ký tự đổi id → mất liên kết lịch sử, orphan.
- C (đã chọn): ID deterministic từ *địa chỉ nguồn* (path/URI). Cùng địa chỉ → cùng id → re-index sạch; id con (section) deterministic nên upsert đè đúng.
**Trade-off:** Đổi tên/di chuyển nguồn tạo id mới và để lại record cũ stale. Chấp nhận có ý thức vì rename hiếm.
**Khi nào xem lại:** Nếu rename/move trở nên thường xuyên, hoặc cần dedup theo nội dung thật → cần content-addressing + reconciliation.

---

## Section 4: Anti-Patterns — Những Gì KHÔNG Làm

### Import SDK vào use-case layer hoặc model core
Thoạt nhìn: gọi thẳng SDK trong use case là nhanh nhất.
Thực tế: business bị cột vào vendor; đổi backend phải sửa use case; test phải dựng SDK thật.
Rule: use-case layer và model core không import SDK vendor. Mọi I/O đi qua capability contract.
Dấu hiệu vi phạm: thấy import SDK ngoài lớp adapter; use case nhận `host`/`api_key` thay vì nhận một contract object.

### Offload blocking sang thread rồi gọi đó là async-native
Thoạt nhìn: edge handler đã async, có `await` khắp nơi → trông như async.
Thực tế: vẫn chạy trên *một* threadpool mặc định chung; bước CPU nặng và đường serving tranh nhau pool → latency cascade.
Rule: I/O-bound thật → dùng client async thật; CPU-bound → executor *riêng có giới hạn*, không dùng chung pool mặc định. Không thêm offload-to-thread mới trong use-case layer.
Dấu hiệu vi phạm: offload-to-thread rải khắp orchestration; một limit concurrency duy nhất cho mọi loại tải.

### Fallback im lặng sang mock/in-memory/file ở production
Thoạt nhìn: "service vẫn chạy" nghe an toàn hơn "service chết".
Thực tế: caller dùng kết quả từ mock (mất semantic) hoặc in-memory (mất durability) mà tưởng thật — failure nguy hiểm nhất của cả hệ.
Rule: production fail-fast khi backend chính hỏng; degraded chỉ ở dev/test hoặc khi explicitly allow. Health surface báo unhealthy khi degraded.
Dấu hiệu vi phạm: cờ "cho phép fallback mock" bật mặc định ở production; degraded reason không rỗng nhưng vẫn nhận traffic; thiếu strict-mode guard ở startup.

### Interface phình to cho "trông có vẻ abstraction"
Thoạt nhìn: một interface lớn gom hết CRUD + claim + log là gọn.
Thực tế: vi phạm ISP — module chỉ cần 2/10 method vẫn phải phụ thuộc cả interface; đổi một method ảnh hưởng mọi caller.
Rule: một contract = một năng lực mô tả được bằng một câu không có "and". Có "and" → tách contract.
Dấu hiệu vi phạm: một interface > 5–6 method không liên quan nhau; caller chỉ dùng một phần nhỏ interface nó nhận.

### Tạo alias/compat mới cho code mới
Thoạt nhìn: thêm một alias để code cũ vẫn chạy là vô hại.
Thực tế: alias tích tụ thành lớp compat nằm trên runtime path, làm mờ ranh giới "cái gì đang chạy thật vs cái giữ để migrate".
Rule: alias cũ được phép tồn tại như backward-compat, nhưng *không tạo alias mới*; code mới import trực tiếp từ vị trí chính tắc.
Dấu hiệu vi phạm: file mới import từ lớp compat/legacy; xuất hiện re-export trong code không phải shim.

### Delete-rồi-recreate khi thay thế dữ liệu (non-atomic replace)
Thoạt nhìn: muốn thay nội dung thì xóa hết cũ rồi ghi mới.
Thực tế: crash giữa delete và recreate → mất dữ liệu, trạng thái lệch, chỉ reprocess mới sửa.
Rule: ghi-đè trước (id deterministic), *prune phần thừa sau*; chỉ đánh dấu "hoàn tất" khi cả dữ liệu chính lẫn metadata cuối thành công.
Dấu hiệu vi phạm: `delete(id)` rồi `recreate(...)` trong cùng một flow ghi.

### Để exception trong fire-and-forget task bị nuốt im lặng
Thoạt nhìn: spawn task chạy nền xong là quên.
Thực tế: exception trong task không được await sẽ biến mất; job fail mà không ai biết, future treo, slot concurrency leak.
Rule: mọi task nền phải được track + có exception handler; nhóm task song song phải cancel + drain anh em khi một cái fail; shutdown phải drain task đang chạy *trước khi* đóng tài nguyên dùng chung.
Dấu hiệu vi phạm: spawn task mà không giữ tham chiếu; gather không xử lý exception; tài nguyên dùng chung đóng trước khi task active xong.

### Tăng concurrency tổng để chữa bottleneck chưa biết nằm ở đâu
Thoạt nhìn: chậm thì tăng worker.
Thực tế: nếu nghẽn ở rate-limit AI / pool DB / latency vector store, tăng worker làm nghẽn nặng hơn và cạn pool.
Rule: phải có metric per-stage để biết bottleneck thật trước khi tăng; tách limit theo từng loại việc.
Dấu hiệu vi phạm: chỉ có một limit concurrency tổng; không có per-stage counter trong health/metrics.

---

## Section 5: Unresolved — Những Gì Còn Để Ngỏ

### Async-native vs sync-có-executor
Tension: async-native cho concurrency thật, không tốn threadpool — NHƯNG kéo theo dependency rủi ro và effort lớn; sync-có-executor đơn giản hơn — NHƯNG giới hạn concurrency thật.
Hiện đang: offload blocking sang threadpool chung; chỉ một vài bước song song thật.
Khi nào cần quyết định: khi backlog làm threadpool saturation khiến đường serving timeout lúc ingest nặng, hoặc trước khi bật scale production.

### Fail-fast vs degraded fallback ở production
Tension: fail-fast bảo vệ tính đúng (không phục vụ kết quả từ backend sai) — NHƯNG giảm availability; degraded giữ service sống — NHƯNG có thể phục vụ kết quả sai mà caller không biết.
Hiện đang: degrade-and-continue + lộ qua reason + health báo unhealthy; cờ cho phép mock fallback default bật.
Khi nào cần quyết định: trước khi production phục vụ traffic thật — cần strict-mode + policy per-dependency.

### Freshness/latency của index so với nguồn
Tension: scanner polling đơn giản và độc lập (không cần hạ tầng event) — NHƯNG latency tối đa = chu kỳ scan và liệt kê toàn bộ nguồn tốn kém khi corpus lớn; event-driven nhanh hơn — NHƯNG thêm phụ thuộc hạ tầng.
Hiện đang: polling theo chu kỳ cố định + đối chiếu toàn bộ nguồn mỗi lần; job chỉ nằm in-memory queue (mất nếu restart trước khi claim).
Khi nào cần quyết định: khi tần suất cập nhật cao làm scanner thành choke point, hoặc khi cần SLO "nội dung mới searchable trong X phút".

### Concurrent claim / terminal-status race khi scale ngang
Tension: cần scale nhiều instance — NHƯNG claim hiện là đọc-rồi-ghi (không atomic lock) và trạng thái cuối không gắn với "ai đang xử lý" → job cũ có thể ghi đè trạng thái của job mới.
Hiện đang: dedup *per-process*; claim atomic chỉ chứng minh ở single-thread; chưa có định danh attempt (claim id).
Khi nào cần quyết định: ngay khi chạy >1 instance với cùng scope nguồn.

### Model core portable vs tốc độ phát triển
Tension: model core thuần (không framework) cho portability tối đa — NHƯNG mất validation/serialization sẵn của framework; giữ framework nhanh hơn — NHƯNG core dính một framework.
Hiện đang: model core dùng một framework validation (tradeoff chấp nhận cho tốc độ).
Khi nào cần quyết định: chỉ khi model core phải dùng được *ngoài* service này (portability thành yêu cầu cứng). **[INFERRED]** Không nên làm sớm.
