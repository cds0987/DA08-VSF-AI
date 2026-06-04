# CONSTRAINTS — Ràng buộc cứng cho repo production mới

> **Mục đích:** KHÔNG phải best practices hay guidelines. Đây là những thứ nếu vi phạm sẽ tạo technical debt nghiêm trọng hoặc bug production — rút ra từ prototype, viết ở mức **transferable sang stack/cấu trúc bất kỳ**.
>
> **Cách đọc:** Ràng buộc nêu bằng *vai trò* (xem vocabulary trung tính trong [MINDSET.md](./MINDSET.md)), không bằng tên thư mục/class. Chỗ `Trong prototype:` chỉ là minh hoạ. Phân biệt: **constraint cứng (never)** ở file này — guideline mềm (prefer) ở nơi khác.

---

## Section 1: Dependency Direction — Không Được Vi Phạm

```text
        Edge layer            (nhận request ngoài: validate, gọi use case, map response)
          │ chỉ phụ thuộc xuống
          ▼
      Use-case layer          (orchestration; KHÔNG có logic SDK)
          │
          ▼
   Capability contracts  ◄────  Adapters   (hiện thực contract; ĐƯỢC dùng SDK vendor)
          │
          ▼
       Model core             (model + rule; KHÔNG phụ thuộc framework/SDK)

   Composition root           (nơi DUY NHẤT biết tất cả & chọn adapter theo env)
```

Mũi tên là chiều phụ thuộc *được phép*. Adapter phụ thuộc contract + model core. Không có mũi tên đi ngược lên.

**Use-case layer không import SDK**
Nghĩa là: lớp orchestration không import client của vendor (object store, vector DB, RDBMS, AI provider...).
Cách đúng: inject qua capability contract; use case chỉ gọi method của contract.
Lý do cứng: nếu use case biết SDK, đổi backend phải sửa business và mọi test phải dựng SDK thật → mất khả năng thay thế.
Trong prototype: use-case layer không import vector/DB/AI SDK; mọi I/O qua contract.

**Model core không import framework**
Nghĩa là: model core không import web framework, ORM, hay SDK vendor.
Cách đúng: model core chỉ chứa model + rule thuần (vd policy "khi nào một bản ghi indexing bị coi là stale").
Lý do cứng: model core là ngôn ngữ chung nhiều layer/team dựa vào; dính framework làm nó không tái dùng và kéo lệch business theo vendor.
Trong prototype: model core dùng một framework validation cho model (tradeoff chấp nhận) nhưng không dính web/ORM/SDK.

**Edge layer không tự build dependency, không chạm internal của composition root**
Nghĩa là: handler không tự khởi tạo client backend, không với tay vào implementation cụ thể bên trong object đã wire.
Cách đúng: composition root wire sẵn; handler chỉ gọi use case đã expose.
Lý do cứng: nếu edge tự build, có 2 nơi quyết định implementation → fallback/degraded state không nhất quán, health surface không phản ánh đúng.

**Adapter không gọi ngược use-case layer**
Nghĩa là: adapter chỉ hiện thực contract + phụ thuộc model core; không import use case.
Lý do cứng: phụ thuộc vòng phá khả năng test và thay thế từng lớp độc lập.

**Lớp compatibility/legacy không nằm trên runtime path chính**
Nghĩa là: composition root và adapter không nên import factory/implementation từ lớp shim/legacy.
Cách đúng: factory chính tắc thuộc lớp được sở hữu rõ (composition root hoặc adapter layer); shim chỉ phục vụ test/entrypoint cũ.
Lý do cứng: shim trên runtime path làm mờ ranh giới "đang chạy thật vs giữ để migrate", giảm tính replaceable.
Trong prototype: composition root vẫn còn import factory store từ lớp compat — **gap đã biết, chưa đóng**; repo mới không được lặp lại.

---

## Section 2: Runtime Boundaries — Không Được Thay Đổi Hành Vi

**Search response schema (contract với consumer)**
Contract: mỗi kết quả phải đủ định danh đơn vị + định danh document + tên hiển thị + tóm tắt + *nội dung đầy đủ* + đường dẫn phân cấp + **cả hai loại lineage URI** (artifact đã xử lý + nguồn gốc) + điểm số. Có correlation id cho mỗi request.
Không được: bỏ field lineage hay nội dung đầy đủ; đổi tên field; trả tóm tắt thay cho nội dung.
Nếu cần thay đổi: cập nhật doc contract + thông báo consumer trước khi merge; version hóa nếu breaking. Đây là phần nhiều team tích hợp vào → phải ổn định.

**Fallback behavior khi backend unavailable**
Contract: backend chính không sẵn sàng → ghi lý do rõ; health surface báo unhealthy.
Không được: fallback im lặng sang mock/in-memory/file rồi báo ok ở production; nuốt warning fallback.
Nếu cần thay đổi: thêm strict-mode + policy per-dependency (cái nào degrade được, cái nào fail-closed).

**Health/readiness phản ánh degraded state**
Contract: degraded ⇒ trả mã unhealthy (không phải ok); payload lộ đủ chỉ số vận hành + backend identity + lý do degraded.
Không được: báo ok khi backend chính hỏng; thêm dependency mới mà không hook vào health.
Nếu cần thay đổi: mỗi backend mới phải hook vào health.

**Document id generation**
Contract: id deterministic theo *địa chỉ nguồn*; id con (đơn vị) deterministic theo id cha + thứ tự; id trong vector store dẫn xuất deterministic từ id con.
Không được: đổi sang ngẫu nhiên hay content-hash mà không migration — sẽ collision/orphan với data đã index; vỡ idempotent reprocess.
Nếu cần thay đổi: coi là data migration (reindex + reconciliation), không phải code edit.

**Thứ tự ghi để giữ consistency**
Contract: đánh dấu *đang xử lý* → ghi-đè dữ liệu chính (id deterministic) → *prune phần thừa* (đơn vị dư từ bản cũ dài hơn) → đánh dấu *hoàn tất* → cập nhật metadata → ghi job log.
Không được: delete-rồi-recreate; đánh dấu *hoàn tất* trước khi dữ liệu chính + metadata cuối thành công.
Nếu cần thay đổi: giữ invariant "không hoàn tất nếu bước cuối fail" và "đơn vị dư bị prune khi bản mới ngắn hơn".

**Embedding dimension ↔ index binding**
Contract: định danh collection/index encode dimension; ghi vector validate đúng dimension, mismatch phải raise rõ.
Không được: ghi vector sai dimension vào index hiện hữu; coi đổi dimension như config edit bình thường.
Nếu cần thay đổi: đổi model/dimension là migration — cần reindex/cutover/rollback plan.

**Security/resource guards của I/O nguồn**
Contract: allow-list nguồn (chặn truy cập chéo ngoài phạm vi cho phép); chặn path traversal; *validate kích thước trước khi đọc toàn bộ vào memory*.
Không được: viết I/O adapter mới (kể cả async) mà bỏ bất kỳ guard nào; đọc body trước khi check size.
Nếu cần thay đổi: extract guard thành logic dùng chung cho mọi path (sync + async); review I/O change như security-sensitive.

**Pipeline quality gate**
Contract: mọi thay đổi ảnh hưởng đến parser, splitter, caption prompt, embedding model, vector index, reranking, hoặc search policy phải chạy qua một bộ eval tối thiểu có câu hỏi vàng + expected source lineage.
Không được: merge thay đổi retrieval chỉ vì kiểm thử thủ công "trông đúng"; đổi prompt/model/splitter mà không đo lại source correctness và no-answer behavior.
Nếu cần thay đổi: cập nhật bộ câu hỏi vàng hoặc ghi rõ vì sao thay đổi chưa ảnh hưởng đến retrieval semantics.

**Deploy verification**
Contract: sau deploy phải chứng minh phiên bản mong muốn đang chạy bằng tag/digest/image thực tế trên runtime, không chỉ bằng trạng thái thành công của CI.
Không được: dùng tag mutable như `latest` cho production; pin image bằng cơ chế không được verify; bỏ qua bước kiểm tra pod/container đang chạy image nào.
Nếu cần thay đổi: cập nhật runbook deploy và thêm bước verify sau rollout (image, health, migration state).

**Runtime config compatibility**
Contract: các config có quan hệ ngữ nghĩa phải được validate cùng nhau lúc startup hoặc trước khi nhận traffic.
Không được: để provider/base URL/model name sai, embedding dimension/index mismatch, hoặc missing credential chỉ lộ ra khi request thật chạy.
Nếu cần thay đổi: thêm startup validation, test config sai phổ biến, và lộ backend identity qua health mà không lộ secret.

---

## Section 3: Code Structure — Đặt Đúng Vai Trò, Không Đặt Sai Lớp

> Bảng theo *vai trò*, không theo tên thư mục. Repo mới ánh xạ vai trò sang cấu trúc của mình.

| Loại code | Thuộc vai trò | KHÔNG được nằm ở | Lý do |
|---|---|---|---|
| SDK client vendor | Adapter layer | use-case layer, model core, edge layer | Cô lập vendor; đổi backend không sửa use case |
| Model + business rule | Model core | lớp compat, lớp tiện ích chung | Phải framework-neutral, là source-of-truth chung |
| Orchestration một luồng | Use-case layer | lớp legacy wrapper, edge layer | Một nơi mô tả "hệ làm gì", không trộn edge/wiring |
| Capability contract | Lớp contract riêng | inline trong adapter hay use case | ISP: contract nhỏ, tách khỏi implementation |
| Validate request + map response | Edge layer | use-case layer, adapter layer | Edge chỉ validate + map; không chứa business |
| Chọn implementation + wiring | Composition root (duy nhất) | edge layer, từng module tự build | Một nơi chọn adapter theo environment |
| Config / secret | Lớp config + validate lúc startup | hardcode trong code | Runtime config qua env; validate sớm |
| Mock / in-memory / fixture | Test + adapter test-only | production runtime path | Mock/file là dev/test only, không xuất hiện ở production |
| Schema + migration | Lớp schema + thư mục migration có version | tạo bảng ad-hoc trong code | Migration idempotent, có index bắt buộc, có rollback note |
| Strategy theo loại đầu vào (vd parser theo format) | Adapter layer (registry/router) | use-case layer, rải `if type==` trong flow | Thêm loại mới không sửa use case |
| Deploy/runbook logic | Delivery/operations layer | application business code | Deploy phải verify image/config/migration nhưng không làm bẩn use case |

---

## Section 4: Pre-Commit Checklist

Tự hỏi trước khi commit. Bất kỳ câu nào "no" → không merge.

1. **Code chạy được với toàn bộ backend là mock/in-memory không?**
   No → dependency đang hardcode vào backend thật; inject qua contract + thêm fallback build.

2. **Có SDK-specific import nào trong use-case layer hoặc model core không?**
   Có → chuyển SDK xuống adapter, định nghĩa/dùng contract.

3. **Thay đổi có giữ đúng chiều phụ thuộc (edge→use case→contract←adapter→model core) không?**
   No → refactor để mũi tên một chiều; xóa import ngược.

4. **Nếu đổi API contract hoặc DB schema — đã cập nhật doc contract (và thông báo consumer nếu ảnh hưởng) chưa?**
   No → cập nhật doc trước khi merge.

5. **Health/readiness còn phản ánh đúng degraded state không? Dependency mới đã hook vào health chưa?**
   No → thêm lý do degraded + đảm bảo báo unhealthy khi degraded.

6. **Có thêm offload-to-thread mới trong use-case layer, hoặc fire-and-forget task không được track/handle exception không?**
   Có → dùng client async thật cho I/O; track task + handler; nhóm song song phải cancel+drain khi fail.

7. **Failure path có ghi job log (status failed) + cập nhật trạng thái document failed không? Timeout/cancel có làm leak slot concurrency hay treo future không?**
   No → thêm ghi log + cập nhật status trong nhánh lỗi; giải phóng slot/future ở finally.

8. **Reprocess cùng document có idempotent không (id con deterministic, ghi-đè đúng, đơn vị dư bị prune)? Có giữ thứ tự ghi-đè-trước-prune-sau không?**
   No → dùng id deterministic + prune; không delete-rồi-recreate.

9. **Có tạo alias/compat mới, hay import từ lớp legacy/shim cho code mới không?**
   Có → import trực tiếp từ vị trí chính tắc; không tạo alias mới.

10. **Test có cover edge/failure (input rỗng/null, dependency lỗi, boundary, race/idempotency) không, hay chỉ happy path?**
    No → thêm test 2 tầng (general + edge).

11. **I/O change có giữ đủ guard (allow-list nguồn, path traversal, size-before-read) không?**
    No → thêm guard dùng chung; không đọc body trước khi validate size.

12. **Thay đổi có thêm một luồng vào/ra mới ngoài các luồng đã định nghĩa không?**
    Có → đó là bug hoặc dev tool; không thêm luồng mới mà chưa cập nhật doc kiến trúc.

13. **Thay đổi có ảnh hưởng parser, splitter, caption, embedding, index, rerank, hoặc search policy không?**
    Có → chạy pipeline eval gate; kiểm tra expected source lineage, no-answer behavior, và latency tối thiểu trước khi merge.

14. **Có quyết định Day 0 mới hoặc thay đổi quyết định cũ không?**
    Có → cập nhật [NEW_REPO_DECISIONS.md](./NEW_REPO_DECISIONS.md) trước khi merge; không để quyết định kiến trúc chỉ nằm trong code hoặc chat.

15. **Thay đổi có ảnh hưởng Docker/Kubernetes/CI/deploy/configmap/secret/migration entrypoint không?**
    Có → verify image được pin đúng, pipeline có build artifact tương ứng, rollout thật sự chạy image mới, health sau deploy đúng, và migration không chạy ad-hoc.

16. **Thay đổi có đổi provider, model, dimension, endpoint, backend mode, hoặc credential policy không?**
    Có → thêm/cập nhật startup validation và test config compatibility; không để lỗi này chỉ xuất hiện ở request production đầu tiên.

17. **Thay đổi có tạo storage path mới, hoặc thêm bước tốn chi phí đáng kể (AI/OCR/embedding) không?**
    Có → khai báo consumer + retention cho storage path mới (không tạo dead/write-only storage); thêm/cập nhật trần chi phí + metric cost (không để chi phí không trần).
