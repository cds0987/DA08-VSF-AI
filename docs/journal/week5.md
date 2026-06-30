# Tuần 5 (26/06 → 30/06) — Embed migration, bug qwen8b, và loạt "giết doc" tận gốc

Học sâu theo commit, **timeline**. Tuần này có **bug ngầm kinh điển nhất repo** (qwen8b giả-multi-
collection — im lặng suốt nhiều ngày vì 1 đặc tính toán học của model che mất nó), cộng 1 chuỗi "giết
doc" tận gốc dạy cách trace lỗi xuyên 2 service. Kết bằng quyết định kiến trúc dựa số liệu + dọn docs.

---

## 26–27/06 — Embed migration 4b→8b: revert rồi reapply ⚠️

### `Revert` rồi `Reapply` "chuyển embedding qwen3-4b → 8b (3 provider, hết engine_overloaded)"
- **Vì sao chuyển:** model 4b liên tục báo lỗi `engine_overloaded` trên các provider OpenRouter dùng —
  8b là bản lớn hơn, có nhiều provider host hơn, ổn định hơn.
- **Revert rồi reapply trong thời gian ngắn:** dấu hiệu của 1 thay đổi *đúng hướng nhưng chưa đủ điều
  kiện* — đổi xong phát hiện vấn đề khác (rất có thể là tiền đề cho chuỗi bug "giết doc" dưới đây, vì
  đổi embed model kéo theo đổi luôn cách gọi API + dimension), revert để chặn lan, rồi sửa nốt phần phụ
  thuộc xong mới reapply.
- **Học:** Đổi 1 thành phần cốt lõi (embedding model) không bao giờ là "đổi 1 dòng config" — nó kéo
  theo toàn bộ chuỗi: dimension, cách gọi API, tương thích collection cũ. Revert ngay khi nghi ngờ thay
  vì cố chữa cháy tại chỗ là quyết định đúng.

## 27–28/06 — Embed dim 2560→4096 native (bỏ MRL-truncate)

### `feat(embed): 8b dim 2560→4096 NATIVE (full chất lượng, bỏ MRL-truncate)`
- **Bối cảnh kỹ thuật quan trọng để hiểu bug bên dưới:** qwen3-embedding-8b là model **Matryoshka
  (MRL — Matryoshka Representation Learning)** — đặc tính của MRL là vector ở **bất kỳ độ dài cắt nào**
  (truncate) từ đầu vector gốc vẫn là 1 embedding HỢP LỆ và **vẫn tương đối gần đúng về mặt cosine** với
  vector full-dimension. Trước đó hệ dùng dim 2560 (cắt từ 4096 gốc) để tiết kiệm storage — giờ đổi
  sang dùng full 4096 cho chất lượng tối đa.
- **Học:** Đặc tính "cắt vẫn hợp lệ" của MRL là **con dao 2 lưỡi** — tiết kiệm được storage, nhưng cũng
  chính là thứ khiến 1 bug nghiêm trọng *không gây lỗi rõ ràng nào* trong nhiều ngày (xem ngay bên dưới).

## 28/06 — Multi-collection shard + BUG qwen8b giả-multi-collection ⚠️⚠️⚠️ (bug nguy hiểm nhất repo)

> Mục tiêu ban đầu: scale embed throughput bằng cách chia corpus ra **5 model, 5 collection riêng**
> (shard round-robin theo hash document_id), mỗi model 1 vector-space — ý tưởng đúng, nhưng có 1 lỗ hổng
> ẩn trong code route khiến tính năng **chạy "thành công" nhưng hoàn toàn sai về bản chất** trong nhiều ngày.

### `e2a8a398` fix(ai-router): embeddings route theo `body['model']` (KHÔNG hardcode qwen8b) — phát hiện + fix gốc bug
- **GỐC BUG (nguyên văn từ commit):** `router.embeddings()` trong ai-router **hardcode** gọi
  `resolve('embed')` — bất kể request gửi lên yêu cầu model nào (`e5large`/`bge-m3`/`pplx`/`te3s`),
  router luôn resolve về model `embed` mặc định = **qwen8b**. Nghĩa là **MỌI** request embed, dù
  rag-worker tưởng đang gửi cho 4 model khác nhau để ghi vào 4 collection khác nhau, **tất cả đều thực
  sự được qwen8b xử lý**.
- **VÌ SAO BUG NÀY IM LẶNG SUỐT NHIỀU NGÀY (đây là phần quan trọng nhất để hiểu):**
  1. qwen8b là model **Matryoshka** (xem mục trên) — vector của nó **cắt ngắn vẫn hợp lệ**.
  2. Router còn truyền tham số `dimensions` xuống API call (lẽ ra để model *đích* trả đúng số chiều nó
     cần) — nhưng vì thực chất luôn là qwen8b xử lý, nó dùng đặc tính Matryoshka để **CẮT vector của
     chính nó cho khớp đúng số `dimensions` yêu cầu** → ví dụ request cho "bge-m3" (1024 chiều) thực ra
     nhận lại **vector qwen8b bị cắt còn 1024 chiều**.
  3. Vector cắt đó **vừa khít kích thước** ô chứa trong collection Qdrant của bge-m3 → **upsert thành
     công, 0 lỗi, 0 cảnh báo** ở mọi tầng (rag-worker, ai-router, Qdrant đều không thấy gì sai).
  4. **Bằng chứng phát hiện ra (đo định lượng):** `cos(stored_e5large_vector, qwen8b_tươi) = 0.96` —
     vector "tưởng là của e5large" lưu trong collection thực ra gần như TRÙNG với vector qwen8b mới sinh
     → tức **không phải e5large nào cả, toàn bộ là qwen8b cải trang**. Gửi `model='e5large'` so với
     `model='qwen8b'` cho cùng văn bản trả về **vector Y HỆT NHAU**.
  - Hệ quả thực: "multi-collection 5 model" thực chất là **5 collection cùng chứa vector qwen8b** (cắt
    ở các độ dài khác nhau) — không hề có đa dạng model như thiết kế, search đa-collection chỉ đang
    hỏi-1-model-5-lần dưới vỏ bọc.
- **Đã làm (fix):** `capability_alias = body['model']` → resolve THẬT theo từng model
  (qwen8b→`embed`, e5large→`embed_e5large`, te3s→`embed_te3s`...). routing.yaml: 5 capability embed
  dùng `adaptive_balanced` (rải đều mọi key) thay vì banded cố định (band 250K nhỏ so token embed →
  dồn hết vào key-1, 4 key còn lại bỏ phí, burst 5-embed/query đập 1 key → 429/tail 54s).
- **Học (bài học giá trị nhất repo):** **Một đặc tính toán học "tốt" của model (Matryoshka graceful
  degradation) có thể VÔ TÌNH che giấu hoàn toàn 1 bug routing nghiêm trọng** — vì hệ thống "trông như
  đúng" ở mọi điểm đo bề mặt (không lỗi, dimension khớp, upsert OK). Bug loại này **chỉ lộ ra khi đo
  trực tiếp nội dung vector** (cosine similarity giữa 2 nguồn), không lộ ra qua log/test thông thường —
  dạy bài học: **khi nghi ngờ "config có hiệu lực không", đo dữ liệu THẬT, đừng tin log "không lỗi".**

### `43455bec` refactor(embed): dẹp hardcode model + gate drift xuyên-service — sửa tận gốc kiến trúc
- **Đã làm:** Viết `infra/ci/embed_model_lint.py` (CI gate mới): assert
  `embeddings.yaml(active) ⊆ contract.EMBED_MODELS/MODEL_TAGS(dim/tag) ⊆ routing.yaml(alias/capability) ⊆ catalog`
  — bất kỳ chỗ nào thiếu/lệch = **CI đỏ trước khi lên prod**. Gate này bắt đúng *class* bug vừa xảy ra
  (khai báo model trong config nhưng code không thực sự route tới được nó — bị âm thầm thay bằng model khác).
  Đổi `embeddings.yaml`: field "primary" → **"anchor"** (không còn đặc quyền trong shard; mọi model là
  **peer ngang nhau**; "anchor" chỉ còn neo 3 việc kỹ thuật: bootstrap engine, fingerprint runtime,
  fallback collection khi tắt shard-read).
- **Vì sao code vậy:** Gốc thật của bug không chỉ là 1 dòng `resolve('embed')` sai — là cả **tư duy nền
  tảng "có 1 model chính (primary)"** sót lại từ kiến trúc single-collection cũ, dù code đã chuyển sang
  multi-model. "Primary" ngầm định trong đầu người viết code rằng có 1 model đặc quyền — chính tư duy đó
  dẫn tới việc hardcode `resolve('embed')`.
- **Học:** Khi sửa 1 bug, hỏi thêm: **"giả định kiến trúc nào đã đẻ ra bug này?"** — sửa dòng code thì
  hết triệu chứng, nhưng nếu giả định nền (ở đây: "có 1 model chính") còn đó, bug tương tự có thể tái
  diễn ở chỗ khác. Đổi tên "primary"→"anchor" là **sửa luôn cái khung tư duy**, không chỉ sửa code.

### `75ca7f45` + `85e0cfc9` đo recall → QUYẾT giữ single qwen8b
- **Đo sau khi đã fix bug:** recall@1 multi-collection shard = **0.53**, recall@1 single qwen8b =
  **0.73** (chênh +0.20). Per-model riêng: qwen8b 0.73 ≫ bge-m3 0.58 > te3s 0.42 ≈ pplx 0.41.
- **Quyết định:** `MULTI_EMBED_ENABLED 1→0` — **quay về single qwen8b cho production**, dù multi-
  collection vừa được sửa đúng kỹ thuật.
- **Học:** Sửa đúng bug không có nghĩa là **nên giữ tính năng đó**. Multi-collection giờ chạy đúng (mỗi
  model thật sự là chính nó) — nhưng đo cho thấy **shard làm recall TỆ HƠN** vì các model yếu (te3s,
  pplx) kéo điểm trung bình xuống mà không bù lại được bằng đa dạng. Quyết định kiến trúc cuối cùng phải
  dựa **số đo sau-fix**, không dựa "tính năng đã chạy đúng kỹ thuật" — đúng kỹ thuật ≠ đáng dùng.

## 28/06 — Chuỗi "giết doc" tận gốc (3 bug riêng biệt, cùng triệu chứng "doc fail")

### `d2123717` fix(ai-router): embed est = MAX per-text (KHÔNG sum batch) — 503 oan
- **GỐC (nguyên văn):** Khi re-ingest, 7/14 doc lỗi `503 no_capacity`. Code ước lượng token cho 1 batch
  bằng cách **CỘNG TỔNG** độ dài mọi text trong batch (`SUM` ~8300 token cho 100 chunk/batch) rồi so
  với `context_length` của model (bge-m3 = 8192) → vượt trần → `feasible_model` **loại oan** model này
  dù từng text riêng lẻ chỉ ~200 token, hoàn toàn vừa context.
- **Bug thật:** `context_length` là giới hạn **PER-TEXT** (mỗi văn bản embed độc lập, không phải tổng
  cả batch cộng dồn) — code áp nhầm logic "tổng cả batch" vào 1 giới hạn vốn áp dụng "từng phần tử".
- **Học:** Khi 1 API xử lý batch (nhiều item trong 1 request), **luôn xác định rõ giới hạn áp ở cấp độ
  nào** (per-item hay per-request) trước khi viết logic ước lượng — nhầm cấp độ tạo ra lỗi *oan* (loại
  bỏ thứ hợp lệ) khó tái hiện vì chỉ xảy ra khi batch đủ lớn.

### `5018d404` fix(rag-worker): embed ép `encoding_format=float` — GỐC CUỐI TypeError-NoneType ⚠️ (lỗi xuyên 2 service)
- **Đã thử fix trước đó ở ai-router** (ép `encoding_format=float`) — tưởng xong, nhưng đo lại dưới tải
  vẫn còn **18% fail @ concurrency=120**.
- **Trace tận gốc (đọc traceback tới đúng dòng SDK):**
  ```
  TypeError: 'NoneType' object is not iterable
    File ".../openai/resources/embeddings.py", in <parser>
      for embedding in obj.data:   <-- obj.data = None
  ```
  - **Chuỗi nhân quả thật:** rag-worker (phía GỌI API) **không tự set `encoding_format`** → OpenAI SDK
    client-side mặc định gửi yêu cầu **base64** kèm theo **gắn sẵn 1 post-parser** kỳ vọng decode
    base64 từ response.
  - Khi gateway (ai-router) bị shed/degrade lúc peak in-flight (burst 100 request) và trả về
    **HTTP 200 nhưng `data=null`** (degrade nhưng vẫn 200, không phải lỗi rõ ràng) → post-parser của
    SDK chạy `for embedding in obj.data` ngay TRONG hàm `create()`, **TRƯỚC** khi code rag-worker kịp
    tự kiểm tra `res.data` rỗng hay không → `TypeError` xảy ra **bên trong thư viện**, không map được
    thành lỗi "transient" (tạm thời, nên retry) → bị xếp loại **permanent** → **doc bị giết hẳn**, không retry.
  - Fix trước ở ai-router (ép giá trị trả về dùng `float`) sửa đúng **nội dung** response, nhưng KHÔNG
    đổi được việc **SDK phía rag-worker tự quyết định parse kiểu gì dựa trên CÁI NÓ GỬI ĐI** (vẫn gửi
    yêu cầu base64) — phải sửa ở **cả 2 đầu**: caller (rag-worker) phải tự khai rõ `encoding_format=float`
    khi gửi, không dựa vào default ngầm của SDK.
- **Học (quan trọng nhất về debug xuyên service):** Một lỗi "đã fix" ở 1 phía của hợp đồng API
  (server/gateway) có thể **chưa đủ** nếu phía kia (client/caller) vẫn dựa vào **default ngầm định**
  của thư viện thay vì khai báo tường minh. *"Tôi đã sửa contract"* khác *"caller đã tuân theo contract
  tường minh"* — luôn kiểm tra cả 2 đầu khi lỗi liên quan tới định dạng trao đổi giữa 2 service.

### `5bf99f4a` fix(rag-worker): miễn rate-limit per-IP cho `/api/search` + `/api/ingest` — chat 429 ⚠️
- **GỐC (nguyên văn, đo định lượng):** rate-limit edge-guard theo per-IP (mặc định 60 request/60s =
  ~1/giây) bị áp **NHẦM** lên cả `/api/search` — endpoint này **không phải** đường vào từ internet, mà
  là **RPC nội bộ** do mcp-service gọi (qua mạng compose). Vì mcp gọi search từ **1 IP cố định duy
  nhất** trong nội bộ → toàn bộ traffic search của MỌI người dùng cùng bị tính chung vào 1 "IP" đó →
  bị bóp xuống còn ~1/giây. Đo thực tế: dưới tải chat 5 QPS, **65% lượt search bị 429** (162 lần 429 so
  với 87 lần 200 OK) → mcp `rag_search` fail → query-service retry rồi bỏ cuộc → **chat trả về RỖNG
  (0 token)** — quan sát được trên Langfuse. **KHÔNG phải nghẽn CPU hay do chạy 1 instance** như giả
  định ban đầu (đáng để ý: triệu chứng "chat rỗng dưới tải" rất dễ bị đoán nhầm là vấn đề hiệu năng/scale).
- **Đã làm:** rag-worker không hề expose ra internet (chỉ mcp-service/document-service gọi qua mạng
  compose nội bộ) → **không có "edge" nào cần per-IP rate-limit bảo vệ** cho các path RPC nội bộ này →
  miễn rate-limit riêng cho `/api/search` và `/api/ingest`, **giữ nguyên** body-size guard (413) và giữ
  rate-limit cho các path khác (vẫn cần bảo vệ nếu có path public).
- **Học:** **Rate-limit per-IP giả định mỗi IP = 1 người dùng thật** — giả định này VỠ khi traffic đi
  qua 1 proxy/service trung gian gom nhiều người dùng lại thành 1 IP nguồn (service-to-service call).
  Áp rate-limit "mặc định an toàn" lên path nội bộ mà không xét bản chất traffic = tự bóp nghẹt chính
  mình. Phải phân biệt rõ **edge (public, cần per-IP)** vs **RPC nội bộ (đã có auth riêng, đo theo
  thực thể khác — không nên đo theo IP)**.

## 28–29/06 — Scale ingest, bỏ per-worker distill, systemeval, load benchmark

- **`1465b201` doc.access delete-cascade chết do NATS "consumer already bound"**: 2 consumer cùng tên
  cố bind 1 lúc (do thiết kế lại nửa vời) → NATS từ chối bind thứ 2 → cascade-delete (xoá vector khi
  xoá doc) không chạy → đốt 110% CPU idle do retry loop. Sửa tận gốc đặt lại đúng 1 consumer/durable-name.
- **Scale ingest:** OCR chuyển từ semaphore cứng sang `AdaptiveConcurrencyLimiter` (AIMD elastic — cùng
  tư duy AIMD đã dùng cho ai-router tuần 4); embed batch song song hoá; `rag-ingest-worker` scale ×8
  cô lập khỏi `/api/search` (ingest và search không tranh tài nguyên nhau); đẩy throughput chạm trần
  thật của VM 16-core.
- **`perf(query-service): bỏ per-worker distill LLM → verify_answer trích per-direction`**: bỏ 1 bước
  LLM-call phụ (distill mỗi worker) mà gộp việc trích xuất vào bước verify chính → giảm 53% latency
  câu nặng (multi-worker), giữ accuracy ~75%. Flag mặc định TẮT (`WORKER_DISTILL_MULTISTEP=OFF`) — đổi
  hành vi mặc định một cách thận trọng.
- **`systemeval/` + bộ 450 câu + HF data-repo**: dựng harness eval toàn-hệ dùng chung nhiều máy.
- **Load benchmark 800–1200 user**: đo bằng Little's Law (in-flight = QPS × latency) — kết luận hệ
  **thừa sức** ở tải thật, nghẽn là **latency tầng reasoning xếp hàng**, không phải rate-limit/HTTP.

## 29–30/06 — Docs refactor verify từ code

- Phát hiện hàng loạt docs cũ lệch code thật (chat endpoint thật khác đường ngoài tưởng; MOSA mặc định
  TẮT; rag-worker "ingest-only" đã sai từ lâu; `department` đã bị bỏ khỏi JWT/DB) → gom toàn bộ docs về
  1 cấu trúc, mỗi file bắt buộc trỏ `code-refs` về đúng file code đã đọc.
- **Học:** Bug qwen8b (tuần này) và docs lệch code (cuối tuần) là **cùng 1 loại bệnh ở quy mô khác
  nhau** — hệ thống "trông như đúng" (config có vẻ đủ, docs có vẻ đầy đủ) nhưng thực chất không khớp
  điều đang thực sự chạy. Bài học chung: **chỉ tin cái đo được/đọc được trực tiếp từ thực thể đang chạy
  (code/vector/log thật), không tin mô tả về nó.**

---
### Đọng lại tuần 5
- **Bug qwen8b là bài học giá trị nhất**: một đặc tính "tốt" của model (Matryoshka) có thể che giấu
  hoàn toàn 1 lỗi routing nghiêm trọng — không log nào báo, chỉ lộ khi đo trực tiếp vector.
- **"Đúng kỹ thuật" ≠ "đáng giữ"** — sau khi sửa multi-collection đúng, đo số vẫn cho thấy nên bỏ.
- Lỗi xuyên 2 service (encoding_format) dạy: sửa 1 đầu hợp đồng chưa chắc đủ, **kiểm cả 2 phía**.
- Rate-limit "mặc định an toàn" có thể tự bóp nghẹt chính mình nếu áp nhầm vào RPC nội bộ.
- Toàn bộ tuần là minh chứng cho nguyên tắc cuối cùng: **code/data thật là bằng chứng duy nhất.**
