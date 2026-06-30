# Tuần 4 (19/06 → 25/06) — Hiệu năng + chất lượng: nhiều thử-sai có số liệu

Học sâu theo commit, **timeline**. Tuần này có rất nhiều **revert có chủ đích** — đặc điểm chung: mọi
tối ưu đều **đo bằng số trước khi giữ**, và khi số xấu thì revert không nuối tiếc. Đây là tuần "khoa học
thực nghiệm" rõ nhất trong cả 5 tuần.

---

## 19–21/06 — Selector ai-router thế hệ 2: elastic_banded → adaptive_balanced

### `4339751b` elastic_banded selector — co giãn theo tải
- **Đã làm:** Mỗi key có pool slot in-flight (Redis ZSET atomic, tự hết hạn hold treo); active-set = W
  key có tải-tích-lũy thấp nhất (even-rotation/swap); **W tự nở/co theo tổng in-flight** (elastic).
  Dispatch theo least-inflight.
- **Vì sao:** Banded rotation cố định (tuần 3) chia băng tĩnh — không phản ứng khi tải lệch thực tế
  giữa các key theo thời gian thực.
- **Vì sao code vậy:** Redis ZSET cho phép "ai đang tải bao nhiêu" là dữ liệu **dùng chung, atomic**
  giữa nhiều worker process — không thể giữ state này in-memory vì ai-router chạy multi-worker.

### `a2e8f905` adaptive_balanced — TPM cho OpenAI · AIMD cho OpenRouter ⚠️ (thay thế elastic_banded)
- **Đã làm:** Nhận ra **2 loại key có trần khác bản chất**, cần 2 cơ chế riêng:
  - **OpenAI**: có TPM (token-per-minute) cố định công bố → dùng **TPM-headroom** (đếm token đã dùng
    trong phút hiện tại, rải đều theo ngân sách còn lại).
  - **OpenRouter** (đa-upstream, không công bố TPM cố định): **AIMD tự dò trần qua tín hiệu 429**
    (Additive-Increase/Multiplicative-Decrease — giống TCP congestion control: thành công → tăng dần
    +1, gặp 429 → giảm mạnh ×0.5).
- **Vì sao code vậy:** Không thể áp 1 công thức cho 2 loại key — TPM là **biết trước** (đọc số), AIMD
  là **dò bằng phản hồi** (không biết trước, học qua lỗi). Tách 2 cơ chế đúng bản chất từng nhà cung cấp.
- **Học:** Đây là bài học elastic_banded không có: **đo lường trực tiếp (TPM) tốt hơn ước lượng gián
  tiếp khi có thể** — chỉ dùng AIMD (dò mò) khi *không* có cách biết chính xác trần thật.

## 22–23/06 — Rerank diversity + OCR vector-chart

### `1e68afdd` rerank diversity cap/doc — chống 1-doc thống trị top-k
- **Bug & gốc rễ:** Eval lộ: 1 query trả về **5 chunk cùng 1 tài liệu** (doc nhỏ nhưng được index đúng,
  rerank lại ưu ái nó quá mức) → các tài liệu liên quan khác bị loại hoàn toàn dù cũng đúng.
- **Đã làm:** Thêm bước **chọn đa dạng tài liệu sau rerank**: lấy pool rộng hơn (`final_k * pool`), rồi
  chọn `final_k` với **tối đa N chunk/doc** (`RERANK_MAX_PER_DOC`), điền phần dư nếu thiếu. Mặc định
  TẮT (`max_per_doc=0`), bật bằng `RERANK_MAX_PER_DOC=3`. 15 test.
- **Vì sao code vậy:** OOP + no-hardcode — tham số hoá ngưỡng thay vì hardcode "tối đa 3" cứng, và mặc
  định tắt để không đổi hành vi khi chưa rõ tác động.
- **Học:** "Rerank đúng điểm số" không tương đương "kết quả tốt cho người dùng" — **độ đa dạng nguồn**
  là 1 chiều chất lượng khác mà điểm relevance đơn thuần không đo được. (Kết quả: recall thực tế 3/8→6/8.)

## 23–24/06 — Chuỗi tối ưu latency có-số (perf "A fast-path")

### `57d26481` A fast-path: triage→1-step rag, bỏ heavy planner (~9s, 41% latency)
- **Đã làm:** Thêm `_fast_triage` (model nhẹ, capability `triage`) phân loại RAG-đơn vs OTHER **trước**
  heavy planner. Nếu RAG đơn → plan cố định 1-step `rag_retrieve`, **bỏ hẳn heavy planner** (tiết kiệm
  ~9s = 41% latency). Mọi case còn lại (so sánh/mơ hồ/đơn nghỉ/off-topic/nhạy cảm/follow-up) vẫn đi
  heavy planner đầy đủ. **Lưới an toàn:** nếu verify trả `NEED_MORE` (cần thêm bước) → replan dùng
  heavy planner (bắt được trường hợp fast-triage phân loại nhầm).
- **Vì sao code vậy:** Không phải mọi câu hỏi cần plan phức tạp — phân loại sớm + rẻ (model nhẹ) để né
  chi phí lớn (planner nặng) cho phần lớn câu đơn giản, nhưng vẫn có đường thoát an toàn khi đoán sai.
- **Học:** Mẫu hình **"cổng rẻ trước, đường nặng có lưới an toàn"** — tối ưu latency mà không hy sinh
  độ đúng, vì sai thì tự sửa qua replan.

### `782c25e4` //hóa answer 7 model đa-pool → `eb019a44` REVERT ⚠️
- **Đã làm (thử):** Rải answer/synth qua nhiều model/pool để tránh nghẽn 1 upstream lúc tải cao.
- **Bug & gốc rễ:** Deploy live → fast-path RAG **ngắt quãng trả RAW DATA thô** (~50% số lần). Gốc:
  `answer` node dùng `astream_verify_answer` (cần format có verdict + reasoning đặc thù); model
  `gpt-oss-120b` (1 trong 7 model rải) **không tuân theo đúng format đó** → code có fail-safe, khi parse
  format thất bại thì trả thẳng dữ liệu thô ra cho người dùng thấy.
  - Đáng chú ý: **probe test "answer-format đơn" PASS** nhưng **"verify_answer-format" lại FAIL** — vì
    đây là 2 format khác nhau, probe đơn giản không phát hiện được lỗi ở format phức tạp hơn.
- **Đã làm (sửa):** Revert về `deepseek` single cho answer/synth (đã chứng minh ổn). Giữ A fast-path
  (vẫn 3/3 sạch khi dùng deepseek). Kết luận: **//hóa answer cần model "cùng họ format"**, không thể
  rải tự do qua model khác kiến trúc.
- **Học (quan trọng):** Test/probe phải khớp đúng **API/format thật** đang dùng trong production path —
  1 probe đơn giản hơn pass không đảm bảo path phức tạp hơn cũng pass. Khi rải tải qua nhiều model, phải
  đảm bảo *tất cả* các model tuân thủ cùng 1 contract output, không chỉ "cũng là LLM giỏi".

### `37cdc540` revert //hóa deepseek+xiaomi 50/50 — xiaomi p99 15s kéo tail xấu ⚠️
- **Đã làm (thử):** Chia tải 50/50 giữa 2 model cho path "think" để giảm nghẽn deepseek.
- **Đo thật @150 request:** deepseek p99 cải thiện 12.99s→8.78s (đúng cơ chế, giảm tải đúng) **NHƯNG**
  xiaomi/mimo p99 lại **15.21s + success rate rớt 125/150→84/150** → vì có 1 model chậm trong mix nên
  **p99 TỔNG xấu đi**, dù model còn lại nhanh hơn.
- **Đã làm (sửa):** Revert routing answer/plan/synth về deepseek-flash làm primary (giữ xiaomi chỉ cho
  `save_mode` overflow — lúc đó chấp nhận chậm hơn vì đang ở chế độ tiết kiệm). Giữ nguyên cơ chế
  `_pick_model_split` (hạ tầng) + viết test sẵn cho khi có model thứ 2 đủ nhanh ngang deepseek.
- **Học:** **p99 của một pool = p99 của model CHẬM NHẤT trong pool đó**, không phải trung bình. Thêm
  model "có vẻ tốt" vào pool song song có thể làm xấu đuôi latency tổng dù model đó tốt hơn ở trung
  bình — phải đo p99 cả tổ hợp, không chỉ đo riêng từng model.

### `eba7ab6d` revert 2-worker — gây "peer closed" cắt SSE 148/150 ⚠️
- **Đã làm (thử):** `uvicorn --workers 2` để tăng throughput xử lý song song.
- **Bug:** Test 150 request → `RemoteProtocolError: peer closed connection without complete body` cho
  **148/150** — server cắt giữa chừng kết nối SSE đang stream (regression nghiêm trọng).
- **Đã làm (sửa):** Về lại 1 worker (known-good 150/150). Ghi rõ: multi-worker + SSE streaming cần điều
  tra riêng (uvicorn `timeout-keep-alive` / proxy buffering) **trước khi** thử bật lại.
- **Học:** **SSE/streaming kết nối dài KHÔNG tương thích ngầm định với multi-worker** nếu không tự cấu
  hình đúng (sticky routing, keep-alive) — đừng tăng worker theo phản xạ "nhiều worker = nhanh hơn" cho
  service có streaming connection.

## 22–23/06 — Chiến dịch test đối kháng (red-team chất lượng)

- Đo trực diện câu hỏi đối kháng (ACL bypass, prompt injection/LEAK, đơn vị tiền tệ USD/VND lẫn lộn,
  memory horizon, streaming bị cắt) → ghi nhận kết quả thật (không tô hồng): CA2 ACL 6/6 (an toàn),
  LEAK gần 100% bị rò info nhạy (xấu), đơn vị tiền tệ loạn (CU1), RAG ảnh 0% ban đầu.
- **`61856319` Revert "MEM-3 thiếu conv_id → STATELESS"** ⚠️: thử sửa rồi **tự revert ngay trong cùng
  campaign** — vì điều tra sâu hơn cho thấy hành vi "không có `conv_id` thì tiếp tục hội thoại gần
  nhất" là **contract hợp lệ đã có test cũ công nhận từ trước**, không phải bug như tưởng ban đầu.
  - **Học:** Trước khi "sửa" 1 hành vi nhìn-như-bug, kiểm tra xem nó có phải **hợp đồng cố ý** (có test
    cũ bảo vệ) hay không — sửa nhầm contract đã có thể gây regression nơi khác.
- Kết quả không sửa hết ngay — gom thành **plan fix phân tầng P0–P3** chờ duyệt mới làm (đúng nguyên tắc
  "không tự ý mở rộng sửa khi chưa duyệt").

## 23–24/06 — Contract gate liên-service (3/4 seam)

- **jwt-contract** (Seam 2/4): hợp đồng claims + gate ACL JWT liên-service.
- **http-contract** (Seam 3/4): gate client dict ↔ server Pydantic của hr-service.
- **mcp-contract** (Seam 4/4): khoá shape kết quả tool MCP (mcp→query).
- **Học:** 3 seam này trực tiếp ngừa lại đúng loại lỗi đã gặp ở sự cố 16/06 (DSN lệch giữa 2 repo, mcp
  hybrid vs collection cũ) — viết gate **sau khi đã bị đau**, không phải phòng ngừa lý thuyết.

---
### Đọng lại tuần 4
- **Mọi tối ưu phải đo bằng số trước khi giữ** — 3 lần thử (xiaomi 50/50, gpt-oss đa-pool, 2-worker) đều
  có lý do hợp lý lúc bắt đầu, đều **bị số liệu thật bác bỏ**, đều revert dứt khoát.
- **p99/đuôi latency của 1 pool = quyết định bởi thành phần chậm nhất**, không phải trung bình.
- **Probe/test phải khớp đúng path/format thật đang chạy** — probe đơn giản pass không bảo chứng path phức tạp.
- **SSE streaming có ràng buộc ngầm với hạ tầng** (multi-worker, keep-alive) — không suy diễn theo trực giác chung.
- Trước khi sửa 1 thứ "nhìn như bug", kiểm tra nó có phải **hợp đồng cố ý** đã có test bảo vệ không.
