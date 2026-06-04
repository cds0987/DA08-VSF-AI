# DAY0_CHECKLIST — Phải chốt trước commit production đầu tiên

> **Mục đích:** Ngăn repo mới lặp lại những lỗi setup đã ngốn thời gian ở prototype. Đọc sau [MINDSET.md](./MINDSET.md), trước khi viết implementation đầu tiên không tầm thường.
>
> Đây KHÔNG phải feature roadmap. Đây là checklist setup tối thiểu làm cho mọi việc kỹ thuật về sau rẻ hơn.
>
> **Cách viết:** nêu theo *vai trò* (xem vocabulary trung tính trong [MINDSET.md](./MINDSET.md)), không theo tên thư viện/biến cụ thể. Chỗ `Trong prototype:` chỉ là minh hoạ. Mỗi mục đã chốt → ghi thành block trong [NEW_REPO_DECISIONS.md](./NEW_REPO_DECISIONS.md). Trạng thái mỗi mục: `[ ]` chưa quyết · `[x] DECIDED` · `[~] DEFERRED (owner + điều kiện revisit)`.

---

## 1. [ ] Quyết định mô hình runtime (concurrency)

Chọn *một* mô hình trước khi implement ingest/search:

- async-native cho I/O ngay từ ngày 1, HOẶC
- code sync với executor *riêng có giới hạn* cho từng loại việc.

Không lấy "edge handler async + offload-to-thread tùy tiện" làm kiến trúc mặc định — đó là "async nửa vời" mà prototype đã trả giá.

Phải quyết cho từng I/O: client metadata (sync hay async), client vector (sync hay async), client storage (bridge hay async), và *cách chạy bước CPU nặng* (parse) — executor riêng hay worker ngoài, không dùng chung pool mặc định.

Output cần có:
- một quyết định viết ra trong repo mới
- tên config cho từng concurrency limit
- test chứng minh hành vi cancellation/shutdown của task nền

## 2. [ ] Migration loop phải chạy được TRƯỚC

Trước khi thêm schema nghiệp vụ, chứng minh vòng migration DB hoạt động:

- tạo một migration rỗng
- apply trên DB sạch
- apply trên DB có dữ liệu cũ
- document giới hạn rollback/downgrade
- thêm index *trong migration*, không phải ad-hoc trong code

Không thêm thay đổi schema nghiệp vụ (định danh attempt, retention job-log, schema document...) trước khi vòng này chạy được.

## 3. [ ] Default production phải fail-closed

Đặt default sao cho thiếu một backend chính làm fail startup ở production:

- thiếu credential AI → fail (trừ khi mock fallback *được phép explicit*)
- thiếu vector backend → fail
- thiếu metadata backend → fail
- health/readiness báo unhealthy khi degraded
- dev/test vẫn được dùng mock/in-memory

Tránh tình huống production *vô tình thừa kế* cờ cho-phép-mock đang bật.
Trong prototype: cờ cho-phép-mock fallback default bật → rủi ro production chạy mock mà không ai để ý.

## 4. [ ] Queue recovery policy

Chọn ngữ nghĩa restart cho job *đã phát hiện nhưng chưa được claim*:

Quyết định ngắn-hạn chấp nhận được:
- dựa polling rediscovery
- document max recovery delay (bằng chu kỳ quét)
- expose chỉ số lần-quét-gần-nhất (bắt đầu/kết thúc/lỗi) + đếm queued/dropped

Bắt buộc trước khi scale backlog lớn:
- queue bền (durable), HOẶC
- bảng pending-job persist, HOẶC
- test rediscovery chứng minh file chưa-claim được phát hiện lại

Không giả định in-memory queue là bền.
Trong prototype: job chỉ nằm in-memory queue → mất hết khi restart trước khi claim.

## 5. [ ] Atomic claim & terminal-status

Thiết kế điều này *trước khi* viết repository ingest:

- một đơn vị công việc chỉ có một claim hợp lệ tại một thời điểm
- dấu thời gian cập-nhật đổi khi claim được acquire (để stale-detection có căn cứ)
- ghi trạng-thái-cuối kèm điều kiện khớp "chủ hiện hành" (claim id)
- ghi trạng-thái-cuối stale phải check số dòng ảnh hưởng và *không* ghi đè được trạng thái mới hơn

Không implement trạng-thái-cuối bằng kiểu đọc-rồi-so-rồi-ghi ở application code (race).
Trong prototype: claim là đọc-rồi-ghi không lock; chưa có định danh attempt → job cũ có thể ghi đè trạng thái job mới.

## 6. [ ] Health contract ngay từ endpoint đầu tiên

Health/readiness phải phản ánh *sự thật vận hành*, không chỉ "process còn sống":

Tối thiểu lộ ra:
- backend identity (đang dùng implementation nào)
- trạng thái degraded + lý do
- độ sâu hàng đợi
- số job bị drop
- số job đang chạy
- chỉ số embedding-coalescer (nếu có embedding)
- áp lực embed của search (nếu có search)
- chỉ số lần-quét-gần-nhất (khi đã có scanner)

Chỉ được báo "healthy" khi runtime đang cấu hình *thực sự* lành mạnh về mặt ngữ nghĩa.

## 7. [ ] Test matrix & optional dependencies

Quyết định phân lớp dependency ngay ngày 0:
- dep bắt buộc cho unit test
- dep optional cho integration
- dep chỉ-có-trong-môi-trường-đầy-đủ

Quy tắc:
- import SDK optional *lazy* (trong khởi tạo/method adapter), không top-level
- test optional dùng cơ chế skip-nếu-thiếu + marker
- test trên mock/in-memory chỉ chứng minh *application logic*
- contract test trên backend thật mới chứng minh *production semantics*

Không coi test pass trên in-memory là proof cho ngữ nghĩa của backend thật.

## 8. [ ] Observability baseline

Mọi operation quan trọng phải có correlation field *từ đầu*:
- định danh document cho ingest
- correlation id cho request/search
- tên stage
- duration mỗi stage
- tên backend cho operation storage/vector/metadata/AI

Chọn structured log sớm nếu hệ thu log production kỳ vọng vậy. Không thể thêm observability *sau* khi backlog đã xảy ra để chẩn đoán chính sự cố đó.

## 9. [ ] Security & resource guards

Guard storage phải tồn tại *trước khi* có code parser:
- allow-list nguồn (chặn truy cập chéo ngoài phạm vi)
- chặn path traversal
- check kích thước *trước khi* đọc body vào memory
- tách prefix cho artifact dẫn xuất (không lẫn với nguồn)
- không log raw nội dung tài liệu / secret

I/O async (nếu có) phải *dùng chung* logic guard với I/O sync — không viết lại thiếu guard.

## 10. [ ] Chiến lược migration embedding model/dimension

Coi đổi embedding model hoặc dimension là *migration*, không phải config edit:
- định danh index/collection encode version hoặc dimension
- có reindex plan (nên reindex từ artifact trung gian để khỏi lặp bước đắt nhất)
- có rollback plan
- có retention policy cho index cũ

Không để đổi dimension thành một config edit tùy tiện ở production.
Trong prototype: từng gặp mismatch runtime do đổi dimension trên index cũ.

## 11. [ ] Delivery and rollout verification

Chốt cách chứng minh production thật sự chạy phiên bản mới trước khi có deploy đầu tiên:

- image phải được pin bằng tag hoặc digest bất biến, không dựa vào `latest`
- pipeline build phải chạy cho mọi thay đổi có thể ảnh hưởng runtime hoặc manifest deploy
- deploy phải verify image đang chạy trên pod/container sau rollout
- deploy phải verify health/readiness sau rollout bằng endpoint thật
- config-only deploy phải có cơ chế rollout/restart rõ ràng
- migration phải chạy trước app hoặc trong bước được kiểm soát, có retry khi backend chưa sẵn sàng
- secret/config bắt buộc phải được sync hoặc validate trước khi app nhận traffic

Không chấp nhận "CI xanh" hoặc "rollout status success" là bằng chứng phiên bản mới đã live.
Trong prototype: từng có deploy xanh nhưng production vẫn chạy code cũ do image transformer không pin đúng image; từng cần tăng timeout/readiness vì backend stateful khởi động chậm hơn giả định.

## 12. [ ] Runtime config compatibility gate

Chốt các cặp config phải được validate cùng nhau:

- AI provider + base URL + model naming convention
- embedding model + embedding dimension + index/collection identity
- vector backend mode + credential + endpoint
- metadata backend mode + migration availability
- storage backend mode + credential + allowed source scope
- mock/in-memory mode + environment class (dev/test/production)

Output cần có:
- startup validation fail-fast cho production
- health payload lộ backend identity và config quan trọng không nhạy cảm
- test cho config sai phổ biến (provider/base URL sai, dimension mismatch, missing credential)

Không để config sai trở thành lỗi muộn ở request đầu tiên.
Trong prototype: từng gặp OpenRouter key gọi nhầm OpenAI endpoint, model name sai format, và embedding dimension không khớp collection.

## 13. [ ] Pipeline acceptance/evaluation gate

Kiến trúc đúng chưa đủ. Repo mới phải định nghĩa cách biết pipeline retrieval có dùng được hay không.

Tối thiểu phải chốt:
- bộ câu hỏi vàng (golden queries) đại diện cho nhu cầu thật
- expected source lineage cho từng câu hỏi vàng
- tiêu chí pass/fail cho recall, precision, no-answer, và source correctness
- ngưỡng score hoặc policy fallback khi không đủ context
- cách đo latency p50/p95 cho ingest và search
- cách phát hiện hallucination hoặc câu trả lời không có grounding
- owner của bộ eval và tần suất chạy lại khi đổi parser, prompt, model, splitter, hoặc index schema

Không chấp nhận "search có vẻ đúng khi thử tay" là bằng chứng chất lượng.
Trong prototype: kiến trúc retrieval đã chuyển sang section + caption, nhưng repo production vẫn cần gate đo chất lượng riêng theo corpus thật.

## 14. [ ] Data retention & artifact lifecycle

Chốt vòng đời cho *từng* loại dữ liệu/artifact, không để mặc định "giữ mãi":
- raw nguồn: ai sở hữu, giữ bao lâu
- canonical artifact (bản đã chuẩn hoá): retention + ai được ghi/đọc
- vector index: dọn khi reindex hoặc đổi model
- job/audit log: retention + prune (tránh phình vô hạn)
- bản ghi metadata của document đã xoá/đổi tên ở nguồn (orphan): reconcile hay giữ?

Output cần có: bảng "loại dữ liệu → owner → retention → cơ chế cleanup".
Không để storage phình vô hạn hoặc orphan tích tụ vì thiếu policy.
Trong prototype: job-log từng phình vì thiếu retention; đổi tên nguồn để lại metadata orphan; chưa có lifecycle rõ cho raw/artifact/vector.

## 15. [ ] Cost/budget guardrail

Chốt giới hạn chi phí cho các bước tốn tiền (AI call, OCR, embedding) *trước khi* scale:
- trần chi phí cho một lần xử lý document (vd số AI call tối đa, có/không OCR)
- ngưỡng cảnh báo khi cost ingest/search vượt mức
- ưu tiên cache + skip để không trả tiền lại cho nội dung không đổi
- policy khi một document quá đắt: từ chối / hoãn / xử lý giảm cấp, thay vì xử lý mù

Output cần có: config trần chi phí + metric cost theo stage + policy khi vượt.
Trong prototype: OCR tài liệu không có text layer rất đắt/chậm, dễ chạm timeout; chi phí chưa có trần rõ.

## 16. [ ] Tiêu chí thoát Sprint 1

Không rời sprint 1 cho đến khi tất cả đúng:
- chiều phụ thuộc sạch (use-case layer/model core không import SDK)
- factory/composition path *không* nằm trong lớp compat/legacy
- hành vi strict fallback đã được test
- ngữ nghĩa claim metadata đã được đặc tả
- queue recovery policy đã viết ra
- health payload cơ bản đã có
- optional dependency policy đã viết ra
- lệnh migration đã chạy ít nhất một lần trên DB sạch
- deploy verification path đã có nếu project có môi trường deploy
- runtime config compatibility gate đã có
- pipeline eval gate đã có bộ câu hỏi vàng tối thiểu
- data retention & artifact lifecycle đã có policy
- cost/budget guardrail đã chốt trần + cảnh báo

---

## Trước khi rời checklist

- [ ] Mọi mục 1–16 ở trạng thái DECIDED hoặc DEFERRED-có-owner.
- [ ] Mỗi mục DECIDED đã có block tương ứng trong [NEW_REPO_DECISIONS.md](./NEW_REPO_DECISIONS.md).
- [ ] Mỗi ràng buộc mới phát sinh đã thêm vào [CONSTRAINTS.md](./CONSTRAINTS.md).
