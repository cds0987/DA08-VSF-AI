# Tuần 2 (05/06 → 11/06) — Lên cloud + CI/CD gated + RAG sống dậy lần 1

Học sâu theo commit, **timeline**. Tuần này = đưa hệ lên 1 VM thật, dựng CI/CD an toàn (auto-rollback),
và **chuỗi fix khiến RAG retrieval chạy được lần đầu** (4 lỗi xếp tầng, sửa lỗi này lộ lỗi sau).

---

## 08–09/06 — MCP hardening + tách hr-service

- **Internal token auth cho MCP** + **tách hr-service thành HTTP proxy** riêng: trước đó hr nằm chung,
  giờ MCP gọi hr-service qua HTTP có token nội bộ — đúng nguyên tắc "mọi call qua gateway có auth", và
  tách domain HR khỏi MCP cho rõ trách nhiệm.
- **`hr_query` MVP** + payroll/benefits/performance intents (self-access + audit): user chỉ xem được
  dữ liệu của chính mình, audit mọi lần đọc.
- **Học:** Service boundary nên cắt theo domain (HR là domain riêng) sớm, đỡ phải tách lại sau khi đã rối.

## 10/06 — Chuỗi 4 fix làm RAG sống dậy lần đầu (đọc theo đúng thứ tự sửa)

> Đây là 1 buổi debug liên tục: sửa lỗi A lộ lỗi B, sửa B lộ lỗi C — đọc tuần tự để thấy cách lỗi xếp tầng.

### 1. `9a3628e1` linh hoạt observability/guardrails — không crash khi thiếu key
- **Đã làm:** Service không có Langfuse/guardrail key thì **chạy tiếp** (degrade), không crash startup.
- **Vì sao:** Một service down vì thiếu env phụ (observability) là quá đắt — env phụ phải optional.
- **Học:** Phân biệt **core dependency** (phải fail-closed) vs **phụ trợ** (phải degrade gracefully) — generic "fail nếu thiếu env" là sai.

### 2. `f53f6d4e` tự ensure JetStream stream + subscribe resilient
- **Đã làm:** Service tự tạo stream nếu chưa có thay vì crash khi NATS chưa kịp sẵn sàng lúc startup.
- **Bug & gốc rễ:** Race điều kiện khởi động — query-service start nhanh hơn NATS bootstrap.

### 3. `14ec2a8f` `_asyncpg_url` chuẩn hóa mọi dialect
- **Bug & gốc rễ:** DSN có thể tới dưới dạng `postgresql://`, `postgresql+psycopg://`... nhưng driver
  `asyncpg` chỉ hiểu 1 dạng → connect fail tùy nơi set env. Chuẩn hóa 1 hàm convert mọi dialect → asyncpg.
- **Học:** (đây chính là tiền thân của vụ DSN gây sự cố 16/06 tuần sau — **chuẩn hóa DSN sớm vẫn không đủ, phải tập trung hoá**.)

### 4. `c9b0dd95` query-service tự chạy migration lúc khởi động
- Tự áp schema `query_svc` khi start thay vì cần chạy tay → đỡ "quên migrate trước deploy".

### 5. `b8511acb` RAG score threshold config-driven + hạ 0.70→0.35
- **Bug & gốc rễ:** Ngưỡng tương đồng 0.70 quá chặt cho embedding/domain thật → mọi kết quả bị loại,
  RAG trả về rỗng dù retrieval chạy đúng. Hạ ngưỡng + đưa ra config (không hardcode) để tinh chỉnh tiếp.
- **Học:** Ngưỡng similarity không có "giá trị đúng phổ quát" — phải đo trên domain/model thật, và phải
  **config được** để chỉnh mà không cần redeploy code.

### 6. `2439f271` RAG retrieval chết do pybreaker `call_async` dựa Tornado ⚠️ (bug khó nhất tuần)
- **Đã làm:** Bỏ `pybreaker`, viết `_AsyncCircuitBreaker` tự chứa (asyncio-native, 3 state closed/open/half-open).
- **Bug & gốc rễ:** `pybreaker>=1.2.0` resolve ra **1.4.1**, mà bản này cài `CircuitBreaker.call_async()`
  **trên Tornado** (`@gen.coroutine`). Service chạy pure-asyncio, không có Tornado → gọi `call_async`
  ném `NameError: name 'gen' is not defined` **trước khi** kịp gọi MCP. Vì `_call_tool()` đi qua breaker
  còn `list_tool_specs()` thì không → triệu chứng khớp 100%: ListTools tới MCP OK, CallTool (rag_search,
  hr_query) luôn chết → bị nuốt thành `langgraph_act_error` chung chung, che mất nguyên nhân thật.
- **Học:** **Một dependency phụ (circuit breaker) ngầm định framework khác (Tornado) có thể giết tính năng chính** mà error message hoàn toàn không gợi ý gì — phải đọc traceback tới tận thư viện, không dừng ở exception bề mặt. Tự viết lại nhỏ + asyncio-native triệt tiêu rủi ro tương thích framework ẩn.

### 7. `d565ea12` `_bind_tools_schema` bỏ sót params của StructuredTool
- **Bug & gốc rễ:** Sau khi breaker hết chặn, lộ lỗi tiếp: bind tool schema cho LLM thiếu field → model
  gọi `rag_search` với **query rỗng**. Sửa bind đủ params.

### 8. `0aeab600` ép `tool_choice=required` vòng ReAct đầu
- **Bug & gốc rễ:** Model có thể **bỏ qua RAG tool** hoàn toàn ở vòng đầu (trả lời thẳng từ tri thức
  nền, sai ngữ cảnh công ty) → ép bắt buộc gọi tool ở vòng đầu tiên.
- **Học (cả chuỗi 6-7-8):** RAG "không trả kết quả" có thể do **bất kỳ lớp nào trong chuỗi**: circuit
  breaker chặn → tool schema thiếu field → model không chọn gọi tool → threshold lọc sạch. Phải kiểm
  từng lớp tuần tự, không đoán 1 phát.

## 10/06 — CD an toàn: stage-gate + auto-rollback + env tập trung

### `278cd8a5` stage-gate smoke chọn-lọc + auto-rollback + torch CPU-only
- **Đã làm:** Deploy job **trap auto-rollback**: ghi điểm rollback = image ID trước khi pull; nếu gate
  fail → retag image cũ + recreate → **prod giữ bản trước, chỉ pipeline đỏ**. Smoke "luồng vàng"
  **chọn-lọc theo phần đổi** (DOC khi doc/user đổi; RAG khi rag/mcp/query đổi; HR khi hr/mcp-hr đổi) —
  không test hết mọi thứ mỗi lần để nhanh. `torch` CPU-only trước requirements (VM không GPU, bớt vài GB image).
- **Vì sao code vậy:** Test hết mọi luồng mỗi deploy quá chậm; nhưng test ngẫu nhiên/không đủ thì rủi ro
  → "chọn-lọc theo phần đổi" cân bằng tốc độ và độ phủ.
- **Học:** **Auto-rollback dựa trên smoke-gate** là tuyến phòng thủ cuối trước khi user thấy lỗi — quan
  trọng hơn việc test có "đẹp" hay không.

### `df2bf873` tập trung env vào `common.env` + commit env-in-git
- **Đã làm:** 1 file biến chung + 6 file per-service, compose `env_file` cascade `[common, <svc>]`.
  **Commit thẳng env vào git** (repo private) → `git reset --hard` đồng bộ env CÙNG code, hết drift.
- **Vì sao code vậy:** Trước đó env rải rác/chỉnh tay trên VM → "code nói 1 đằng, env trên VM 1 nẻo"
  (drift) là nguồn lỗi khó tái hiện kinh điển. Đánh đổi: lộ giá trị config trong git (chấp nhận được vì
  repo private + đây không phải secret thật — secret riêng nằm ở GitHub Secrets).
  - Bỏ override `environment: DATABASE_URL` (từng đè lên `env_file` — 2 nguồn xung đột âm thầm).
  - hr alembic đổi đọc `HR_DATABASE_URL` — hết "split-brain" giữa migrate dùng DSN khác runtime dùng DSN khác.
- **Học:** Khi nghi ngờ "code đúng mà chạy sai" — luôn nghi **env drift** trước. Tập trung 1 nguồn (dù
  phải đánh đổi) thường rẻ hơn chi phí debug drift về sau.

### `353fa43d` provision-once NATS streams + verify-only (hết overlap tận gốc)
- **Bug & gốc rễ:** `jetstream.conf` **không tạo stream** (chỉ là comment) → nhiều service cùng tự
  `add_stream` vào 1 broker → **2 stream khác tên trùng subject = overlap** (message lẫn giữa stream).
- **Đã làm:** Tách **1 service bootstrap one-shot** (`nats-bootstrap`) tạo stream theo contract
  `subjects.md`, idempotent, chạy TRƯỚC mọi service khác (`depends_on: service_completed_successfully`).
  rag-worker/document-service/query-service chuyển sang **verify-only** (`NATS_STREAM_AUTO_CREATE=0`,
  fail-closed: bootstrap fail → service không start → health-gate đỏ → rollback, **không degrade âm thầm**).
  Dev/CI giữ `=1` vì NATS ephemeral mỗi lần.
- **Học:** **"Mỗi service tự lo phần hạ tầng dùng chung" = công thức race condition.** Đúng là tách
  riêng 1 bước provision-once + các service còn lại chỉ verify — và để fail-closed thay vì lặng lẽ chạy thiếu.

### `ce3e1543` chuẩn hóa Alembic cho doc/user + đồng bộ danh tính qua event `user.*`
- **Bug & gốc rễ:** `hr_query` 404 cho user chưa được "seed" thủ công ở hr-service — vì user-service và
  hr-service vốn không đồng bộ identity tự động.
- **Đã làm:** document-service & user-service chuyển sang Alembic thật (bỏ runner tự chế + file `.sql`
  tay). Phát event `user.created/updated/deactivated` (NATS, stream `USER_EVENTS`); hr-service subscribe,
  **lazy auto-create `leave_balance`** khi cần — tất cả **best-effort, không fail-closed** (vì đây là
  đồng bộ phụ, không phải đường ghi chính).
- **Học:** Đồng bộ giữa 2 service nên qua **event**, không qua "nhớ chạy script seed tay"; nhưng đồng bộ
  phụ thì nên **best-effort** chứ không chặn luồng chính — khác hẳn nguyên tắc fail-closed ở NATS bootstrap
  bên trên (đó là hạ tầng *bắt buộc phải đúng*, đây là tiện ích *nên đúng nhưng không bắt buộc*).

## 11/06 — Observability: Langfuse self-host + tracing per-node

### `2ae3a681`→`92c6ba6f` chuỗi Langfuse: low-level client → callback → span lồng nhau
- **Đã làm:** Bắt đầu bằng Langfuse callback chuẩn, sau đó đổi sang **LOW-LEVEL client** (không dùng
  callback) để kiểm soát chính xác span. Thêm `span llm.<node>` bắt được prompt model NHẬN + output model
  NGHĨ; lồng `tool.<name>` span trong `act` node thay vì để Langfuse tự derive từ `on_tool_start`
  (derive tự động bị sai context).
- **Bug & gốc rễ (`bc7d2e1c`):** Usage tracking trước đó chỉ tính khi có model call rõ ràng → câu
  off-topic (không gọi LLM-tool) bị tính **cost $0.00** sai (thực ra vẫn có 1 lần gọi phân loại). Gom
  usage MỌI lần model call vào rollup.
- **Học:** Tracing tự động (callback/derive) tiện nhưng **mất kiểm soát context chính xác** khi pipeline
  có nhiều lớp (node trong node, tool trong act) — đến lúc cần độ chính xác cao thì phải hạ xuống
  low-level client.

### `03c40d27` self-host Langfuse v2 nội bộ VM
- Tự host thay vì dùng SaaS — kiểm soát dữ liệu (corpus/trace nội bộ), nhưng đổi lại phải tự lo
  readiness/migration của chính Langfuse (`LANGFUSE_INIT_ORG_ID` thiếu → 401 ở commit sau).

---
### Đọng lại tuần 2
- **RAG sống được lần đầu nhờ sửa đúng 4-5 lớp xếp tầng** (breaker→schema→tool_choice→threshold) — dạy
  cách debug hệ thống nhiều lớp: sửa từng lớp, đo lại, đừng đoán 1 phát ra nguyên nhân.
- **Hạ tầng dùng chung (NATS stream) phải provision-once + verify-only**, không để mỗi service tự lo.
- **Phân biệt rõ fail-closed (hạ tầng bắt buộc) vs best-effort (tiện ích phụ)** — áp nhầm chiều nào cũng hỏng.
- **Env drift** là nghi phạm số 1 khi "code đúng mà chạy sai" trên VM thật.
