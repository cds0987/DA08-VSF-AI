# LESSONS — Distill từ prototype để build lại không lặp lỗi

> **Mục đích:** Viết cho người (hoặc AI agent) sắp build lại production. Không ngoại giao. Viết ở mức **transferable** — bài học là *general*, `Trong prototype:` chỉ là minh hoạ một lần đã xảy ra.
>
> Phân biệt: **lesson từ mistake** (tránh lần sau) vs **lesson từ discovery** (replicate lần sau). Đọc cùng [MINDSET.md](./MINDSET.md), [CONSTRAINTS.md](./CONSTRAINTS.md), [DAY0_CHECKLIST.md](./DAY0_CHECKLIST.md).

---

## Section 1: Những Gì Đã Thử Và Fail

### Trigger ingest bằng event bus nặng (broker/topic/DLQ)
**Đã thử:** Kích hoạt ingest bằng một event bus với consumer/producer/dead-letter.
**Gặp vấn đề:** Thêm hạ tầng stateful nặng cho bài toán mà nguồn dữ liệu thật ra chỉ là *file nằm trên object store*. Event bus tạo coupling: pipeline không chạy được cho đến khi team khác publish event → mất tính độc lập khởi động.
**Rút ra (mistake):** Chọn cơ chế trigger theo *nơi dữ liệu thật sự nằm*, không theo pattern thời thượng. Polling nguồn tuy có latency nhưng cho pipeline độc lập hoàn toàn — không chờ team khác.
**Dấu vết (prototype):** Code consumer + test của event bus thành dead code; env vars liên quan bị bỏ; nằm trong bảng "off-limits".

### Đơn vị-kỹ-thuật (khối token cố định) làm retrieval unit
**Đã thử:** `parse → clean → cắt token cố định + overlap → embed → index → search` trên từng khối.
**Gặp vấn đề:** Một đơn vị tri thức bị xé thành nhiều khối; search trả mảnh thiếu đầu thiếu đuôi; tài liệu dài sinh hàng nghìn khối khớp theo token-overlap chứ không theo nghĩa; consumer nhận context khó dùng, phải tự phục hồi ngữ cảnh xung quanh.
**Rút ra (mistake):** Đơn vị retrieve phải là đơn vị *nghĩa* do cấu trúc tài liệu định nghĩa, không phải đơn vị *kỹ thuật*. Giải quyết vocabulary mismatch tại indexing time, không phải query time.
**Dấu vết (prototype):** Bước "chunk" còn là thin wrapper "không còn là retrieval unit"; payload vector vẫn đọc được cả schema mới lẫn legacy để tương thích.

### Concurrency bằng thread + bước tuần tự trong critical path
**Đã thử:** Dispatcher dùng thread workers; tóm tắt N đơn vị chạy tuần tự trong vòng lặp (một call/đơn vị nối tiếp).
**Gặp vấn đề:** Mỗi thread chờ network chiếm RAM + scheduling overhead; một document mất hàng chục giây chỉ riêng bước tóm tắt; không retry → rate limit giữa chừng fail cả job.
**Rút ra (mistake + một nửa discovery):** I/O-bound concurrency nên là coroutine, không thread; các bước AI nên song song (gather + semaphore). NHƯNG: chuyển sang async mà vẫn offload mọi blocking I/O sang threadpool **chưa phải async thật** — tốt hơn thread nhưng vẫn dùng *chung một* pool, bước CPU nặng và đường serving giẫm chân nhau. Async-native là đích nhưng *chưa làm xong* vì effort lớn + dependency rủi ro.
**Dấu vết (prototype):** Dispatcher đã chuyển sang event-loop queue + semaphore; tóm tắt đã song song; nhưng offload-to-thread vẫn rải trong orchestration.

### Cấu trúc code flat (gom interface + implementation + fallback một chỗ)
**Đã thử:** Gom store + provider + fallback + interface vào vài file tiện ích chung.
**Gặp vấn đề:** Một file vừa là interface, vừa implementation, vừa fallback policy (vi phạm SRP). Đổi provider kéo theo sửa business; nhiều người đụng cùng file.
**Rút ra (mistake):** Tách theo capability + chiều phụ thuộc *ngay từ đầu* rẻ hơn nhiều so với refactor sau. NHƯNG migration khỏi flat không "free": shim cũ có xu hướng nằm lì trên runtime path vì luôn có việc ưu tiên hơn việc dọn nó.
**Dấu vết (prototype):** Các file tiện ích cũ nay là re-export shim; implementation thật đã chuyển sang adapter layer; nhưng composition root vẫn còn import factory từ shim (gap chưa đóng).

### Đặt access-control/filtering ở lớp retrieval
**Đã thử:** Bảng permission + filter quyền ngay trong retrieval; endpoint trả context có access control.
**Gặp vấn đề:** Trộn business access-control vào một retrieval layer single-tenant làm nó phải biết tổ chức/phòng ban/role — sai trách nhiệm.
**Rút ra (discovery):** Retrieval layer trả raw unit + lineage; access control/filtering là việc của caller tầng trên. Giữ ranh giới trách nhiệm sạch quan trọng hơn "làm hộ" caller. Có thể *để sẵn field* cho ACL tương lai nhưng *không enforce* ở tầng này.
**Dấu vết (prototype):** Bảng permission đã drop; model document vẫn để sẵn field scope/tags (optional) nhưng retrieval không enforce.

### Xem CI xanh là bằng chứng production đã chạy code mới
**Đã thử:** Deploy qua CI/CD, manifest apply thành công, rollout không báo lỗi.
**Gặp vấn đề:** Production vẫn chạy code cũ vì image transformer không pin đúng image; deploy nhìn như thành công nhưng pod không đổi phiên bản. Đây là lỗi nguy hiểm vì mọi tín hiệu bề mặt đều "xanh".
**Rút ra (mistake):** Delivery phải có bước verify sau deploy: image tag/digest thật trên pod, rollout history, health endpoint, và nếu có thể là version/commit trong runtime. Không dùng tag mutable làm nguồn sự thật.
**Dấu vết (prototype):** Có commit riêng để sửa image pin theo SHA và commit riêng để ghi runbook verify-after-deploy.

### Để config provider/index sai chỉ lộ ở runtime
**Đã thử:** Đổi AI provider/model/dimension bằng config deploy.
**Gặp vấn đề:** Provider key gọi nhầm base URL → 401; model name không đúng convention provider; embedding dimension không khớp vector collection. Các lỗi này không phải bug thuật toán nhưng làm pipeline chết hoặc trả sai trạng thái.
**Rút ra (mistake):** Config runtime là contract. Các cặp provider/base URL/model, model/dimension/index, backend/credential phải được validate cùng nhau lúc startup và lộ phần không nhạy cảm qua health.
**Dấu vết (prototype):** Có nhiều commit chỉ để sửa OpenRouter base URL/model format và `EMBEDDING_DIM` mismatch.

### Tạo storage/schema chỉ để ghi mà không có consumer đọc
**Đã thử:** Lưu thêm bảng `document_chunks` trong metadata store.
**Gặp vấn đề:** Bảng trở thành write-only: pipeline ghi vào nhưng retrieval không đọc; thêm migration, code, test, và rủi ro drift mà không tạo giá trị vận hành.
**Rút ra (mistake):** Mỗi storage path phải có consumer rõ ràng hoặc retention/debug purpose rõ ràng. Nếu không đọc, không expose, không dùng để recover, thì đó là dead storage.
**Dấu vết (prototype):** `document_chunks` bị drop bằng migration sau khi xác nhận retrieval chỉ đọc vector store.

---

## Section 2: Những Gì Tốn Thời Gian Hơn Dự Kiến

### Async refactor
Tưởng là: đổi sang async chỉ là thêm từ khoá `async`/`await`.
Thực tế: async đúng nghĩa cần đổi cả dependency stack (client async cho object store/DB/vector/AI) — mỗi cái một rủi ro (có client async là wrapper cộng đồng, không chính thức; có cái chỉ hỗ trợ một backend). Và một loạt bug *chỉ xuất hiện* khi async: exception trong fire-and-forget task bị nuốt; một task tự cancel chính nó làm orphan future khiến caller treo; nhóm song song không cancel anh em làm leak slot concurrency; shutdown drain sai thứ tự (đóng tài nguyên dùng chung trước khi task active xong). Kết quả: dừng ở "async nửa vời".
Lần sau: quyết định dứt khoát từ đầu — async-native (chấp nhận dependency risk, làm phần consistency trước) HOẶC sync + executor *riêng có giới hạn* và *không* giả vờ async. Đừng dừng ở giữa nếu định scale.

### Quản lý dependency / optional imports
Tưởng là: cài hết rồi test xanh.
Thực tế: nhiều dependency là optional/chỉ-có-trong-môi-trường-đầy-đủ (SDK object store, ORM, thư viện ảnh, client vector). Test local fail không phải vì code sai mà vì thiếu dep.
Lần sau: ngay từ đầu quyết định dep nào *bắt buộc* cho unit test, dep nào *optional* cho integration; dùng cơ chế skip-nếu-thiếu có chủ đích + marker rõ; **import SDK lazy bên trong method/khởi tạo adapter**, không import top-level module, để module load không crash khi thiếu dep.

### Test với nhiều backend thay thế
Tưởng là: test một lần trên in-memory là đủ.
Thực tế: in-memory/file/real-backend *không behavior-equivalent* — in-memory mất durability; file behavior khác RDBMS; claim race chỉ lộ ở backend thật dưới concurrency. Test pass trên in-memory **không** chứng minh production đúng.
Lần sau: viết *contract test dùng chung* chạy trên mọi implementation của một contract (in-memory + thật), đặc biệt cho semantics khó: atomic claim, prune phần thừa, dimension mismatch. Đừng coi mock là proof cho production backend.

### Parser cho định dạng visual (tài liệu scan/ảnh cần OCR)
Tưởng là: một thư viện parse được mọi định dạng.
Thực tế: tài liệu không có text layer phải render từng trang rồi OCR qua model — đắt, chậm, dễ chạm timeout. Stack parse là sync/blocking/CPU-heavy, không có API async tốt → không "async hoá" thật được, chỉ cô lập được.
Lần sau: tách loại rẻ (text, sync) khỏi loại đắt (visual/OCR remote) *ngay từ đầu*; cho phần nặng một executor + concurrency *riêng* tách khỏi pool chung; có guard kích thước *trước* khi load vào RAM (tránh OOM).

### Hạ tầng stateful khởi động chậm hơn giả định của CI
Tưởng là: container start là service sẵn sàng trong vài chục giây.
Thực tế: Qdrant/Postgres/MinIO cần start period, readiness delay, PVC mount, collection init, hoặc migration retry. Nếu CI/rollout timeout quá ngắn, deploy fail giả; nếu healthcheck dùng tool không có trong image, service bị đánh dấu unhealthy dù app có thể chạy.
Lần sau: healthcheck phải dùng công cụ có sẵn trong image; stateful dependency cần `start_period`/readiness phù hợp; rollout timeout phải tính cả image pull + dependency startup + migration.

### Migration không được là thao tác ad-hoc của operator
Tưởng là: production có thể chạy migration thủ công khi cần.
Thực tế: deploy tự động cần migration chạy đúng thứ tự, retry khi DB chưa sẵn sàng, và không nuốt signal của process chính. Nếu migration flow chưa được thiết kế, schema drift trở thành lỗi runtime khó debug.
Lần sau: có migration entrypoint hoặc deploy step rõ ràng; migration revision đặt tên dễ đọc; entrypoint dùng `exec` để app nhận signal; dev/test có thể tạo schema nhanh nhưng production phải đi qua migration versioned.

---

## Section 3: Những Quyết Định Đúng — Cần Giữ Lại

### Contract + adapter pattern ngay từ đầu
Lúc đầu tưởng: over-engineering cho một service nhỏ.
Hóa ra: đúng, vì cho phép thay backend (vector/metadata/AI) mà *không sửa use case*; test mock ở mức contract thay vì dựng SDK; nhiều người làm song song.
Giữ lại vì: là thứ duy nhất giữ business không bị cột vào vendor.

### In-memory implementation của mọi backend cho testing
Lúc đầu tưởng: thừa khi đã có backend thật.
Hóa ra: đúng, vì "chạy được với toàn bộ mock/in-memory" thành điều kiện merge; test nhanh, không cần hạ tầng; ép thiết kế phải thật sự inject-able. *Nhưng* nhớ chúng không behavior-equivalent — dùng để test logic, không để chứng minh production.
Giữ lại vì: tốc độ test + ép tính inject-able.

### Một embedding-coalescer dùng chung + cache theo content-hash
Lúc đầu tưởng: premature optimization.
Hóa ra: đúng, vì gom request cross-job thành batch lớn (tận dụng throughput provider), và cache theo content-hash bỏ qua re-embed khi reprocess hoặc khi nhiều document trùng đoạn (footer/disclaimer).
Giữ lại vì: giảm API call + cost rõ rệt, nhất là lúc reprocess hàng loạt.

### Embed ý-nghĩa-nén thay vì raw content
Lúc đầu tưởng: thêm một AI call/đơn vị là đắt và rủi ro.
Hóa ra: đúng, vì khử vocabulary mismatch *tại indexing time*; vector gọn, semantic rõ; consumer đọc nhanh qua tóm tắt nhưng vẫn có nội dung đầy đủ + lineage làm đường lui.
Giữ lại vì: đây là leverage cao nhất cho retrieval quality.

### Document id deterministic theo địa chỉ nguồn
Lúc đầu tưởng: nên hash content cho "đúng" hơn, hoặc ngẫu nhiên cho an toàn.
Hóa ra: đúng, vì id theo địa chỉ làm reprocess idempotent (ghi đè sạch, không duplicate); id con deterministic nên upsert đè đúng. Trade-off rename-tạo-id-mới được cân nhắc có ý thức.
Giữ lại vì: idempotency là nền của reprocess/stale-reclaim; content-hash phá nó mỗi lần sửa nội dung.

### Canonical artifact trung gian có địa chỉ ổn định
Lúc đầu tưởng: lưu thêm bản trung gian là tốn storage thừa.
Hóa ra: đúng, vì cho phép chạy lại từng bước downstream *mà không lặp bước đắt nhất* (parse/OCR); cho debug output từng bước; cho consumer kiểm tra chéo. Lineage nguồn→artifact→đơn vị→vector truy ngược được.
Giữ lại vì: artifact trung gian là chìa khoá reprocess hàng loạt khi đổi prompt/model.

### Ghi-đè-trước / prune-sau (atomic-safe replace)
Lúc đầu tưởng: thay nội dung thì xóa cũ rồi ghi mới là trực giác nhất.
Hóa ra: delete-rồi-recreate *sai* — crash giữa chừng mất dữ liệu, trạng thái lệch. Ghi-đè trước (id deterministic) rồi prune phần thừa là đúng: tại mọi thời điểm dữ liệu vẫn dùng được.
Giữ lại vì: là invariant consistency cốt lõi; đảo lại tái tạo bug mất dữ liệu.

### Eval gate cho retrieval là một phần của kiến trúc, không phải việc làm sau
Lúc đầu tưởng: nếu parser, splitter, caption, embedding, và vector search chạy đúng thì chất lượng retrieval sẽ ổn.
Hóa ra: pipeline có thể đúng về mặt kỹ thuật nhưng sai về mặt sản phẩm: trả nhầm nguồn, bỏ sót câu hỏi quan trọng, không fallback khi thiếu context, hoặc trả đoạn có vẻ liên quan nhưng không đủ grounding.
Giữ lại vì: mọi thay đổi vào parser, splitter, prompt, embedding model, index schema, hoặc search policy đều có thể làm chất lượng retrieval đổi theo cách test unit không bắt được. Repo mới phải có golden queries, expected source lineage, no-answer cases, và latency target ngay từ Sprint 1.

### Verify-after-deploy là invariant vận hành
Lúc đầu tưởng: CI/CD thành công là đủ.
Hóa ra: không đủ. Cần chứng minh đúng artifact đang chạy và đúng config đang active. Nếu không, mọi debug sau đó có thể diễn ra trên phiên bản cũ mà team không biết.
Giữ lại vì: nó rẻ hơn nhiều so với truy lỗi giả trong app khi production chưa hề chạy code mới.

---

## Section 4: Bắt Đầu Lại — Làm Khác Gì Ngay Từ Sprint 1

Ordered theo ưu tiên. Chỉ những thứ có đủ evidence từ prototype. (Bản quyết-định-hoá nằm ở [DAY0_CHECKLIST.md](./DAY0_CHECKLIST.md).)

1. **Quyết định async dứt khoát ngay từ đầu — không nửa vời.** Vì "async + offload-to-thread" để lại threadpool saturation và một loạt bug lifecycle tốn nhiều phiên để vá. Chọn async-native (làm phần consistency trước) HOẶC sync-có-executor-riêng.

2. **Strict production backend policy + fail-fast ngay từ bootstrap.** Vì fallback im lặng sang mock/in-memory/file là failure nguy hiểm nhất ("sống nhưng sai"). Production fail nếu thiếu backend chính; degraded chỉ ở dev/test. Không để cờ cho-phép-mock bật mặc định ở production.

3. **Định danh attempt (claim id) + atomic claim ngay khi thiết kế schema.** Vì claim đọc-rồi-ghi không an toàn dưới multi-instance, và trạng thái cuối không gắn "ai đang xử lý" → job cũ ghi đè trạng thái job mới. Dùng atomic upsert/conditional-update + guard trạng-thái-cuối bằng claim id từ đầu.

4. **Guard kích thước *trước* khi load vào memory — ngày 1.** Vì đọc cả file lớn vào RAM gây OOM. Check size trước khi đọc body; guard nằm trong I/O layer dùng chung cho mọi path.

5. **Retention policy cho bảng job-log ngay khi tạo schema.** Vì log ghi mỗi lần ingest/retry/reprocess → phình không giới hạn. Thêm prune + tham số retention + index trên cột thời gian ngay từ migration đầu.

6. **Structured logging gắn correlation id (document id / request id / stage / duration) từ ngày 1.** Vì không nhìn được lineage nguồn→artifact→đơn vị→result thì không debug lỗi retrieval một cách hệ thống. Mỗi stage log id + duration; mỗi request log correlation id.

7. **Tách concurrency limit theo loại việc, không một limit chung.** Vì bottleneck thật có thể ở nhiều nơi; tăng worker mù làm nghẽn nặng hơn + cạn pool. Định nghĩa limit riêng cho từng stage + expose per-stage counter trong health/metrics.

8. **Guard độ dài đơn vị + sub-split khi vượt ngưỡng, ngay trong bước chia.** Vì tài liệu thiếu cấu trúc → đơn vị quá dài → consumer nhận context vượt giới hạn mà không cảnh báo. Ngưỡng configurable, vượt thì chia tiếp theo ranh giới nhỏ hơn, giữ lineage + thứ tự.

9. **Reliability policy đồng nhất cho mọi AI call (retry+backoff+jitter + cache), ngay từ đầu.** Vì để một số AI call có retry còn số khác không → rate limit giữa chừng fail cả job. Mọi call ra provider nên cùng chính sách.

10. **Lazy import SDK trong adapter + skip-nếu-thiếu cho optional dep — quy ước từ commit đầu.** Vì import SDK top-level làm cả test suite crash khi thiếu dep; tốn thời gian truy nguyên. SDK import bên trong khởi tạo/method adapter; test optional dùng cơ chế skip + marker.

11. **Contract test dùng chung cho mọi implementation của một contract — không chỉ test in-memory.** Vì in-memory/file/real không behavior-equivalent; bug claim-race/prune/dimension chỉ lộ ở backend thật. Một bộ test chạy trên cả in-memory lẫn backend thật cho mỗi contract có semantics khó.

12. **Đổi embedding model/dimension là migration có cutover, không config edit — định từ thiết kế index.** Vì đổi dimension mà chung index gây mismatch runtime. Encode dimension vào định danh index *và* có sẵn runbook reindex/dual-write/rollback; coi là migration.

13. **Đặt eval gate cho retrieval trước khi tối ưu hoặc scale.** Vì search "có vẻ đúng" khi thử tay không chứng minh pipeline đúng. Cần golden queries, expected source lineage, no-answer cases, score/fallback policy, và latency target tối thiểu trước khi gọi pipeline là production-ready.

14. **Pin image bất biến và verify sau deploy từ Sprint 1.** Vì deploy xanh nhưng code cũ vẫn chạy là loại lỗi đốt thời gian nhất: team debug sai phiên bản. Luôn pin SHA/digest, verify pod image, verify health, và expose version/commit nếu có thể.

15. **Validate config compatibility ở startup.** Vì provider/base URL/model name/dimension/index mismatch là lỗi cấu hình có thể phát hiện sớm. Production không được nhận traffic khi các cặp config này mâu thuẫn.

16. **Không tạo storage path nếu chưa có consumer hoặc recovery purpose.** Vì write-only table/log/index làm tăng migration và drift. Mỗi schema mới phải trả lời: ai đọc, đọc khi nào, retention ra sao, dùng để recover gì.
