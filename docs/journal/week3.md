# Tuần 3 (12/06 → 18/06) — ai-router ra đời, leave-chat, và sự cố RAG 0-sources

Học sâu theo commit, **timeline**. Tuần này có 2 trục: (A) xây — ai-router + leave-chat hoàn chỉnh,
(B) **sự cố outage 16/06** — RAG trả 0 nguồn trên prod, 6 lớp nguyên nhân xếp chồng, sửa lớp này lộ
lớp sau, kết bằng đổi triết lý deploy. Đọc kỹ phần B — đây là bài học đắt giá nhất repo.

---

## 12–15/06 — ai-router (Phase 1) + control-plane

- **`feat(ai-router): add OpenAI-compatible AI gateway service (Phase 1)`** — sinh ra ai-router: chuẩn
  hoá MỌI lời gọi LLM/embedding của hệ thống qua 1 gateway OpenAI-compatible, thay vì mỗi service tự
  gọi thẳng OpenAI/OpenRouter. Đây là **mở rộng trực tiếp ý tưởng "AI gateway 1 cửa"** đã đặt nền từ
  tuần 1 (`ai/` trong rag-worker) — giờ tách hẳn thành service riêng dùng chung cho mọi service khác.
- **banded rotation 250K + deepseek blend (think) + save-mode + observability per-key×model**: nhiều
  API key xoay vòng theo băng quota (banded), blend model cho path "think" (reasoning), chế độ tiết
  kiệm khi gần hết quota, và đo riêng từng cặp (key, model) để biết key nào/model nào đang tải.
- **control-plane HITL v1 — drain/resume key + guardrail + audit**: cho người vận hành **rút 1 key ra
  khỏi vòng xoay** (vd key sắp hết quota / bị lỗi) mà không cần redeploy, có audit log.
- **Học:** Tách AI-gateway thành service riêng (thay vì lib dùng chung) cho phép **vận hành** nó độc
  lập (drain key, đổi rotation) mà không đụng code các service gọi nó — đúng lý do tách service.

## 12/06 — security: SSH lockdown qua IAP/WIF

- **`ci+infra: migration-lint gate + codify SSH lockdown into dev-provision.sh`**: thay vì SSH trực
  tiếp (`appleboy` action) bằng key cố định, chuyển sang **WIF (Workload Identity Federation) + IAP
  tunnel** — không còn private key SSH nằm trong CI secret, quyền cấp theo identity tạm thời.
- **Học:** SSH key tĩnh trong CI secret là rủi ro dài hạn (key rò = quyền vĩnh viễn); WIF cấp quyền
  theo phiên, thu hồi tự động — đáng đổi độ phức tạp setup.

## 16/06 sáng — leave-chat: registry 4 rổ + resolve_date deterministic

- **`feat(leave-chat): date-aware draft + editable confirm form`**: model xuất JSON nháp ngày-nhận-biết
  → user sửa được trên form → confirm mới ghi DB thật (không tin model ghi thẳng).
- **`feat(mcp): tool resolve_date — quy đổi ngày deterministic thay vì model đoán`** ⚠️
  - **Bug & gốc rễ:** Để model tự suy luận "thứ 2 tuần sau là ngày mấy" → đôi khi đoán sai (model
    không có lịch thật, suy luận ngôn ngữ tự nhiên dễ lệch 1 ngày quanh ranh giới tuần/tháng).
  - **Đã làm:** Tách thành 1 **tool tính toán thuần** (`resolve_date`) — input "thứ 2 tuần sau" →
    output ngày ISO chính xác bằng code, không qua LLM đoán.
  - **Học:** **Việc gì máy tính làm chính xác 100% (tính lịch) thì đừng giao cho LLM đoán** — dù LLM
    "thường đúng" vẫn có % sai mà người dùng không lường được. Tool-call cho phép tách phần *suy luận
    ngôn ngữ* (LLM) khỏi phần *tính toán chính xác* (code).
- **`feat(hr-leave): Phase 1 — Leave Type Registry 4 rổ (luật LĐ VN) + deduction theo rổ`**: thay vì
  hardcode loại nghỉ rải rác trong prompt, định nghĩa **registry tập trung** 4 rổ (phép năm/ốm/không
  lương/đặc biệt) theo luật lao động VN, mỗi rổ có rule trừ quỹ riêng → Phase 2 (mcp+query+prompt) và
  Phase 3 (FE dropdown) đều đọc từ registry này, không hardcode lặp lại.
- **`feat(leave): chống trùng đơn`** → **`fix(leave-chat): bỏ model tự phát hiện trùng (cảnh báo sai ngày)`**
  ⚠️ *(revert một phần trong cùng buổi sáng)*
  - Thử để model tự cảnh báo trùng ngày → model báo sai (cảnh báo trùng khi thực ra không trùng) →
    bỏ, chuyển hẳn việc check trùng về code (so sánh ngày trực tiếp trong DB), không qua model.
  - **Học:** Cùng 1 bài học với `resolve_date` — lặp lại trong ngày: **đừng để LLM làm việc đối chiếu
    dữ liệu chính xác**, chỉ dùng LLM cho phần hiểu ý định người dùng.

## 16/06 chiều — SỰ CỐ: RAG trả 0 nguồn trên prod (đọc tuần tự — sửa lớp này lộ lớp sau)

> Bắt đầu lúc rebuild mcp-service để thêm `leave_types` (tính năng leave-chat ở trên) — vô tình **phơi
> bày một rollout dở dang** đã nằm im trong code nhiều ngày. Đây không phải 1 bug, là **6 lớp xếp chồng**.

### Lớp 1 — `2102dfae` NameError chặn build
- **Bug:** Merge code đồng đội để lại `grounded_results` (biến không tồn tại) trong `orchestration.py` +
  test ngưỡng RAG lệch logic mới (0.70→0.45) → unit test đỏ → **chặn được deploy ở bước build** (may mắn).
- **Học:** Lớp test/CI đã chặn đúng vai trò — nhưng đây chỉ là bug bề mặt che các lớp sâu hơn còn lại.

### Lớp 2 — `f85b01f1` + `9805829c` mcp hybrid-query vs collection Qdrant cũ
- **Bug & gốc rễ:** mcp-service có code **hybrid search** (dense+sparse) đã viết nhưng **chưa từng
  thật sự deploy** — lần rebuild mcp đầu tiên (do leave_types) mới đẩy code này lên prod. Code hybrid
  giả định mọi collection Qdrant có schema hybrid; nhưng **collection thật trên prod vẫn là dense
  *unnamed* cũ** (chưa migrate). mcp gọi `using='dense'` trên collection unnamed → Qdrant trả **HTTP
  400** → 0 kết quả → tưởng nhầm là data mất.
  - Verify trực tiếp: Qdrant vẫn còn nguyên **21,397 point** — không mất gì, chỉ là cách query sai.
- **Đã làm:** mcp tự phát hiện schema collection (`get_collection()`) trước khi query: có sparse →
  hybrid (dense+sparse); không sparse → dense KHÔNG truyền `using`. Tương thích ngược cả 2 dạng.
- **Học:** **Code mới giả định schema mới, nhưng data thật chưa migrate** = lỗi triển khai kinh điển.
  Bài học thao tác: *luôn verify trực tiếp trên hạ tầng thật (`get_collection`) trước khi tin code đúng*.

### Lớp 3 — `fb306cae` rerank threshold quá chặt
- Rerank đổi sang provider 'llm' + threshold 0.7 → hit hợp lệ bị lọc sạch (giống bug threshold 0.70 ở
  tuần 2, nhưng đây là rerank-stage chứ không phải embedding-stage) → về lexical (mặc định cũ) +
  threshold 0.05 thấp, mở khoá tạm để unblock deploy.

### Lớp 4 — `f89e63f6` DSN thiếu `+psycopg` → NAK-loop → ACL rỗng ⚠️ (lớp khó nhất, hậu quả dây chuyền dài nhất)
- **Bug & gốc rễ (chuỗi nhân-quả 6 bước, nguyên văn từ commit log):**
  `user_access_profile` repo tự định nghĩa `_asyncpg_url` riêng, chỉ thay `+asyncpg`, **bỏ sót
  `+psycopg`** (scheme thật trên VM, do tuần 2 đã chuẩn hóa DSN dùng driver psycopg)
  → `asyncpg.create_pool("postgresql+psycopg://...")` raise **"invalid DSN"**
  → event `hr.employee_profile.updated` xử lý lỗi → **NAK-loop vô tận** (NATS liên tục redeliver)
  → bảng `user_access_profile` **mãi rỗng** (không bao giờ insert thành công)
  → `get_profile()` trả `None` → `department=""` → `allowed_doc_ids` rỗng
  → LangGraph kết luận `"No document access"` → **RAG sources=0**
  → smoke RAG fail × 6 lần liên tục → DEPLOY FAIL.
- **Đã làm:** Dùng lại đúng 1 hàm `_asyncpg_url`/`_import_asyncpg` **dùng chung** từ
  `postgres_document_access_repo` (regex `^postgresql\+[a-z0-9_]+://` xoá MỌI dialect, không liệt kê
  từng cái) — đồng bộ với `notification_repo` & `conversation_repo`. Thêm
  `test_dsn_normalization.py` chặn regression.
- **Học:** Đây là **cùng 1 lớp lỗi đã sửa ở tuần 2** (`_asyncpg_url` chuẩn hóa dialect) nhưng **một repo
  khác tự viết lại hàm riêng** thay vì dùng chung → lệch. → **Logic hạ tầng dùng chung (DSN parsing)
  phải có 1 implementation DUY NHẤT, import lại, không copy-paste mỗi nơi 1 bản.**

### Lớp 5 — `bb3a0912` thiếu hẳn migration cho bảng `user_access_profile` (gốc rễ CHÍNH còn lại)
- **Bug & gốc rễ:** Sau khi DSN đúng (lớp 4), lộ ra: bảng `user_access_profile` **CHƯA TỪNG có migration
  tạo nó** — bảng chỉ tồn tại trong tài liệu `data-schema.md`, không tồn tại thật trong DB.
  → `INSERT` vào bảng không tồn tại → `relation does not exist` → NATS NAK redeliver **vô tận** (hàng
  trăm lần/giây) → flood log + đập DB → query-service nghẽn → RAG 0 sources (lặp lại triệu chứng lớp 4
  nhưng nguyên nhân khác hẳn). Đồng thời ACL non-admin (sếp/nhân viên) mất quyền đọc tài liệu nội bộ vì
  cùng bảng rỗng.
- **Đã làm:** Thêm migration `003_user_access_profile.sql` (idempotent `CREATE TABLE IF NOT EXISTS`,
  đúng theo `data-schema.md`). Khi bảng đã tồn tại, JetStream tự redeliver các event đang kẹt → bảng
  tự populate lại → hết storm.
- **Học:** **Tài liệu thiết kế (`data-schema.md`) mô tả bảng nhưng không có migration tương ứng = bom
  hẹn giờ** — không lỗi cho tới khi có traffic thật chạm vào bảng đó. Đây chính là động lực trực tiếp
  sinh ra `infra/ci/schema_drift_check.py` sau này (code đọc bảng phải có migration, gate trong CI).

### Lớp 6 — `88d7acbc` triết lý deploy sai: rollback nửa vời còn tệ hơn không rollback
- **Bug & gốc rễ (nguyên văn từ commit message):** Một check post-deploy fail → kích hoạt rollback CŨ:
  retag image về bản TRƯỚC + `compose up --force-recreate`. NHƯNG **migration đã tiến lên** (hr_db ở
  revision 0006) trong lúc deploy. Image cũ bị retag **không biết** revision 0006 tồn tại →
  `hr-migrate` exit 255 → nginx kẹt ở "Created" → **toàn site lỗi 521**, trong khi log lại báo nhầm
  "production kept previous version" (rollback "thành công" giả).
  → **"Rollback nửa vời còn tệ hơn không rollback."**
- **Đã làm:** Đổi triết lý deploy hoàn toàn:
  - **PRE-FLIGHT** (trước khi đụng vào stack đang chạy): chạy `alembic current` bằng image MỚI trên
    mỗi service có migration. Nếu không định vị được revision hiện tại của DB → **ABORT TRƯỚC KHI**
    recreate bất cứ gì → prod giữ nguyên bản cũ, không đụng gì cả.
  - **Forward-only on_failure:** khi deploy fail, **KHÔNG** retag/re-migrate/restore — chỉ dừng và báo đỏ.
- **Học (quan trọng nhất tuần):** Khi hệ thống có **state tiến hoá một chiều** (schema migration), thì
  "rollback code" không tự động an toàn nếu state đã đổi — phải kiểm tra **tương thích state TRƯỚC khi
  hành động**, và khi không chắc, **dừng lại** (forward-only) còn an toàn hơn cố "sửa cho xong" bằng
  một hành động có thể phá nhiều hơn.

## 17/06 — Hardening sau sự cố + kích hoạt ai-router cho query-service

- **`57c8a0cf` kích hoạt routing cho query-service**: sau khi ai-router ổn định, đổi query-service từ
  gọi thẳng OpenAI sang gọi qua ai-router — chính thức MỌI LLM call đi qua gateway.
- **`c6375317` bug ngay sau khi bật:** `chat_stream` trùng tên biến với keyword `'stream'` trong code
  → stream vỡ → outcome `NO_INFO` giả (không phải do RAG, do lỗi code response-streaming). Sửa nhanh
  trong 10 phút nhờ regression test asyncio.
- **`security(deploy): bỏ hardcode seed password`**: password seed admin/nhân viên từng hardcode trong
  `deploy.sh` → chuyển sang biến môi trường bí mật.
- **Observability mở rộng:** Prometheus+Grafana per-key (`19d2b1c3`), Alertmanager+alert rules
  (`b7e758a2`), Tempo+Loki+OTel Collector (`8992fa21`) — dựng full quan sát ngay sau sự cố, đúng phản
  xạ "sự cố → đầu tư quan sát để bắt sớm lần sau". cAdvisor thử rồi **gỡ** vì không chạy được trên VM
  cgroup-v2 (`2304e2ec`) — chấp nhận giới hạn hạ tầng, không cố ép.

---
### Đọng lại tuần 3
- **ai-router** chính thức là gateway DUY NHẤT cho mọi LLM call — mở rộng tự nhiên từ ý tưởng AI-gateway tuần 1.
- **resolve_date + chống trùng đơn**: bài học lặp lại 2 lần trong 1 buổi sáng — *LLM giỏi hiểu ý định,
  dở tính toán chính xác*. Tách rõ 2 việc đó bằng tool-call.
- **Sự cố 16/06 là 6 lớp lỗi xếp chồng** — học được: (1) code-mới/data-cũ phải verify trực tiếp hạ
  tầng; (2) logic dùng chung (DSN parsing) không được copy-paste; (3) doc thiết kế không migration =
  bom hẹn giờ; (4) **rollback không kiểm tra state tương thích = rủi ro hơn không làm gì** — pre-flight
  + forward-only an toàn hơn "cố sửa".
