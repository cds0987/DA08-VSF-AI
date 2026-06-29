# Lộ trình sản phẩm — RAG Internal Chatbot

## Tầm nhìn sản phẩm

Xây dựng **chatbot nội bộ** giúp nhân viên công ty tìm kiếm thông tin, tra cứu chính sách, hỏi về HR — nhanh hơn hỏi đồng nghiệp, chính xác hơn tự tìm trong hàng trăm file tài liệu.

Không chỉ là một chatbot — mà là **hệ thống quản lý tri thức nội bộ** có thể mở rộng và tích hợp vào quy trình làm việc thực tế của công ty.

---

## Tại sao đề tài này khả thi

- **Vibe coding**: 6 người, stack rõ ràng (FastAPI + Nuxt 4 + RAG), sprint nhanh
- **Phase sau không phụ thuộc phase trước**: team có thể stop ở bất kỳ điểm nào và sản phẩm vẫn usable
- **Có precedent**: các công ty như Notion, Confluence đều đang build tính năng này — chứng minh nhu cầu có thực

---

## 5 tuần — Lộ trình cụ thể

> 📅 **Kế hoạch chi tiết từng tuần (ai làm gì theo Sprint):** [docs/sprints/](sprints/README.md) — roadmap này = *làm gì + DoD theo Phase*; folder sprints = *lịch thực thi từng tuần*.

### Phase 1 — Core MVP + Cloud Deploy _(Tuần 1–3)_

> **Mục tiêu:** Chatbot hoàn chỉnh, chạy thật trên GCP, nhân viên truy cập được qua domain thực.

**Sẽ làm:**
- Auth: đăng nhập bằng email/password **hoặc Microsoft Account (SSO)**, phân quyền Admin / End User
- Upload tài liệu (PDF, DOCX, TXT, XLSX, CSV, PPTX, Markdown) → tự động xử lý và index
- Giao diện chat: hỏi câu hỏi → bot trả lời + trích dẫn nguồn tài liệu
- Admin upload/xóa tài liệu, theo dõi trạng thái ingestion; không có bước duyệt tài liệu trong MVP
- HR Service: hỏi HR cá nhân, AI tạo draft đơn nghỉ phép, user xác nhận, sếp trực tiếp duyệt
- Guardrails: chặn prompt injection, lọc off-topic, redact PII trong output
- Semantic Cache: cache câu hỏi tương tự (Redis TTL 1h), tiết kiệm ~60% OpenAI API cost
- Deploy lên GCP: GCE + Docker Compose, Cloud SQL, Cloud Storage, HTTPS qua Nginx

> **✅ Đã triển khai thêm (so với plan gốc — cập nhật theo runtime hiện tại):**
> - **Multi-Agent (Orchestrator-Workers)** chạy mặc định trong prod (`AGENT_MODE=orchestrator_workers`), không còn là "phương án Phase 4". Lưu "suy nghĩ của agent" (thoughts/plan/trace) vào `messages.metadata.agent` → xem lại được sau reload.
> - **ai-router** — gateway LLM tương thích OpenAI (multi-pool key OpenAI + OpenRouter, routing theo cost/tải, hot-reload).
> - **Leave WRITE đầy đủ**: tạo/sửa/hủy/duyệt/từ chối + **"Đơn của tôi"** (nhân viên tự xem đơn & trạng thái); event `hr.leave_request.*` đẩy SSE cho sếp/nhân viên.
> - **Notification Center**: thêm **xóa** thông báo (badge unread giảm real-time).
> - **Documents**: **bulk-delete** (chọn nhiều, xóa 1 lần) + phân trang số.
> - **Observability stack**: Prometheus/Grafana/Loki/Tempo/Alertmanager/otel-collector.
> - **Scale**: 8 replica query-service sau nginx `query_pool` (SSE-safe).

**Definition of Done:**

_Auth_
- [ ] Đăng nhập bằng email/password hoạt động
- [ ] Đăng nhập bằng Microsoft Account (SSO) hoạt động
- [ ] Phân quyền Admin / End User đúng — endpoint Admin bị chặn nếu dùng role User
- [ ] Local account có thể reset mật khẩu qua email

_Upload & Ingestion_
- [ ] Admin upload file (PDF, DOCX, TXT, XLSX, CSV, PPTX, MD — tối đa 50MB)
- [ ] Upload xong → status `queued` ngay, trigger ingestion pipeline tự động (không cần duyệt)
- [ ] PDF scan → OCR bằng model OCR đã cấu hình (`OCR_MODEL`), trích xuất được text tiếng Việt
- [ ] OCR/parse xong phải ghi canonical Markdown artifact vào GCS (`artifacts/{document_id}/markdown.md`); downstream chunk/caption/embed đọc lại artifact này, không index trực tiếp từ buffer tạm
- [ ] Qdrant payload lưu cả URI file gốc (`source_uri`) và URI Markdown artifact (`artifact_uri`; mcp-service expose ra `source_gcs_uri`/`markdown_gcs_uri`) để debug, citation, eval và re-index
- [ ] Excel/XLSX → convert từng row thành text có header đúng
- [ ] Upload có chọn classification (Public / Internal / Secret / Top Secret), field lưu vào DB
- [ ] Classification được enforce khi query — Top Secret chỉ uploader xem được, Internal chỉ nhân viên active, Public cho tất cả account

_Q&A Chatbot_
- [ ] Semantic Cache hoạt động — câu hỏi tương tự (cosine similarity > 0.95) trả kết quả từ cache Redis, không gọi OpenAI
- [ ] Hỏi câu hỏi → bot trả lời streaming qua **SSE** (`POST /query`, chữ xuất hiện dần, không đợi toàn bộ)
- [ ] Mỗi câu trả lời kèm nguồn: tên tài liệu + số trang + đoạn văn bản được trích dẫn
- [ ] Sources/citations được lưu trong `query_svc.messages.sources` theo từng assistant message; reload lịch sử hội thoại vẫn hiện đúng source
- [ ] Click vào nguồn → mở document viewer, nhảy đến đúng trang, highlight đúng đoạn text đó
- [ ] Không có tài liệu liên quan → bot trả về "Không tìm thấy thông tin" — không bịa
- [ ] Multi-turn: dùng Summary Buffer — LLM tóm tắt các turns cũ thành 1 đoạn ngắn, giữ nguyên 5 turns gần nhất verbatim → câu hỏi sau luôn hiểu đủ ngữ cảnh mà không tốn quá nhiều token

_HR Personal Q&A_
- [ ] Hỏi ngày nghỉ còn lại / trạng thái đơn nghỉ phép → bot trả lời đúng từ mock data
- [ ] Không thể xem HR data của người khác (filter `user_id` đúng)
- [ ] AI tạo draft đơn nghỉ phép, hỏi lại thông tin thiếu, chỉ nộp sau khi user xác nhận
- [ ] HR Service tạo `leave_requests(status=pending)` và gán `approver_user_id = employees.manager_user_id`
- [ ] Sếp trực tiếp thấy "Đơn cần duyệt" khi có pending requests trỏ về mình; approve/reject đúng quyền bằng `approver_user_id`
- [ ] Không tạo Word/PDF; DB record trong `hr_svc.leave_requests` là đơn chính thức

_MCP Tool Service_
- [ ] mcp-service chạy như MCP server riêng (port 8003), expose 6 tool: `rag_search`, `hr_query`, `leave_write`, `leave_approvals`, `leave_types`, `resolve_date`
- [ ] Query Service agent là MCP client — liệt kê + gọi tool qua MCP; inject `document_ids`/`user_id` (không để LLM tự điền)
- [ ] `rag_search`: mcp gọi rag-worker `/api/search` (rag-worker embed query qwen3-8b + vector search) → rerank (`lexical`/`llm`, fallback an toàn) → Top-K; `hr_query` HTTP proxy gọi HR Service nội bộ và không sở hữu HR data
- [ ] Tool `leave_write` chỉ chạy sau user confirmation (AI tạo draft, user xác nhận mới gọi)

_Admin Dashboard + Analytics (FE — Admin app `frontend/admin`)_
- [ ] Xem danh sách tài liệu + trạng thái ingestion (queued / processing / indexed / failed)
- [ ] Deactivate / Reactivate tài khoản user (xử lý nhân viên nghỉ việc)
- [ ] **Analytics Dashboard** (kéo từ Phase 2 lên): charts volume theo ngày, feedback rate (up/down), top câu hỏi — gọi `GET /admin/metrics`

_Realtime / Notification Center (SSE) (FE — Chat app `frontend/chat`)_
- [ ] Stream SSE `GET /notifications` mở sẵn ngay sau khi đăng nhập (app-level)
- [ ] Tài liệu ingest xong (indexed) → Document Service phát `notify.doc_new` → Query Service đẩy "Có tài liệu mới: X" qua SSE `/notifications` tới **mọi user đang online có quyền xem** (lọc classification/ACL)
- [ ] **Notification Center**: toast realtime + badge số chưa đọc + dropdown lịch sử + mark-as-read (`GET /notifications/history`, `/unread-count`, `POST /{id}/read`)

_Document Viewer + Conversation History (FE — Chat app `frontend/chat`)_
- [ ] Click nguồn → mở **Document Viewer** (PDF.js): nhảy đúng trang + highlight đoạn citation (presigned URL từ `GET /documents/{id}/file`)
- [ ] **Conversation history UI**: list / search / rename / delete hội thoại

_Guardrails_
- [ ] Prompt injection bị chặn — user không thể override system prompt bằng câu hỏi
- [ ] Off-topic filter — câu hỏi không liên quan công việc → bot từ chối lịch sự, không gọi LLM
- [ ] PII trong output bị detect và redact trước khi trả về user

_Feedback & Observability_
- [ ] Thumbs up / down cho từng câu trả lời, lưu vào DB
- [ ] Langfuse trace hoạt động: xem được latency, token cost, retrieved chunks

_Cloud Deployment_
- [ ] Toàn bộ stack chạy ổn định trên GCP GCE bằng Docker Compose (core: nginx, nuxt-chat, nuxt-admin, user-service, document-service, query-service ×8, rag-worker, mcp-service, hr-service, ai-router, nats [JetStream], Qdrant, Redis, app-postgres, Langfuse + overlay observability; frontend/base là Nuxt layer build-time)
- [ ] Cloud SQL PostgreSQL thay thế local DB — data không mất khi restart
- [ ] File upload lưu vào Cloud Storage (GCS), không lưu local
- [ ] Qdrant self-hosted trên GCP, có persistent volume
- [ ] HTTPS hoạt động trên domain **vsfchat.cloud** (TLS kết thúc ở Cloudflare → nginx :80 trên GCE)
- [ ] Langfuse self-hosted trên GCP, IT/DevOps truy cập được
- [ ] Cloud Monitoring alarm hoạt động — cảnh báo IT/DevOps khi GCE CPU > 80% hoặc service không phản hồi
- [ ] Smoke test sau mỗi deploy: 10 câu hỏi mẫu pass toàn bộ trước khi tuyên bố production-ready

---

### Phase 1.5 — Evaluation Checkpoint _(Cuối tuần 3)_

> **Mục tiêu:** Đo chất lượng RAG pipeline trước khi build thêm — biết chắc nền tảng tốt rồi mới đi tiếp.

Evaluation chia thành 4 nhóm — mỗi nhóm đo một khía cạnh khác nhau của sản phẩm.

#### Nhóm 1 — RAG Quality (dùng RAGAS framework)

> Đo chất lượng pipeline RAG. Cần bộ test 20–30 câu hỏi + đáp án mẫu từ tài liệu thực.

| Chỉ số | Ý nghĩa | Ngưỡng production |
|--------|---------|------------------|
| **Faithfulness** | Bot có bịa thông tin không có trong tài liệu không? | **≥ 0.90** |
| **Answer Relevance** | Câu trả lời có đúng trọng tâm câu hỏi không? | **≥ 0.85** |
| **Context Precision** | Chunks retrieve về có đúng không, hay lấy về nhiều đoạn rác? | **≥ 0.80** |
| **Context Recall** | Bot có tìm đúng đoạn tài liệu liên quan không? | **≥ 0.80** |
| **Answer Correctness** | Câu trả lời có đúng so với đáp án chuẩn không? | **≥ 0.80** |

#### Nhóm 2 — Performance

> Đo tốc độ và khả năng chịu tải. Dùng Locust hoặc k6 để test.

| Chỉ số | Ý nghĩa | Ngưỡng production |
|--------|---------|------------------|
| **First token latency** | Thời gian đến khi streaming bắt đầu xuất hiện | **< 2 giây** |
| **P95 response latency** | 95% câu hỏi trả lời xong trong bao lâu | **< 8 giây** |
| **Concurrent users** | Bao nhiêu người dùng cùng lúc mà không giật lag | **≥ 50 users** |

#### Nhóm 3 — Safety & Reliability

> Đo độ an toàn — quan trọng với dữ liệu nội bộ công ty.

| Chỉ số | Ý nghĩa | Ngưỡng production |
|--------|---------|------------------|
| **Hallucination rate** | % câu trả lời có thông tin bịa không có trong nguồn | **< 5%** |
| **Graceful rejection rate** | Khi không có tài liệu liên quan, bot có nói "không biết" không (thay vì bịa)? | **≥ 95%** |
| **Access control accuracy** | Bot có trả nhầm tài liệu restricted cho người không có quyền không? | **100%** |

#### Nhóm 4 — Business Metrics

> Đo adoption và sự hài lòng thực tế — thứ management quan tâm nhất.

| Chỉ số | Ý nghĩa | Ngưỡng mục tiêu |
|--------|---------|----------------|
| **User satisfaction rate** | % câu hỏi được thumbs up | **≥ 70%** |
| **Answerable rate** | % câu hỏi bot trả lời được (không phải "không tìm thấy") | **≥ 80%** |
| **Weekly active users** | Số người dùng trong 1 tuần / tổng nhân viên | **≥ 30%** |

---

**Kết quả evaluation quyết định bước tiếp theo:**

```
Nhóm 1–2 đạt ngưỡng? ──Yes──→ Tiếp tục Phase 2 bình thường
      ↓ No
Investigate nguyên nhân:
  - Faithfulness thấp → prompt engineering, giảm hallucination
  - Context score thấp → tune chunk size / overlap / top-k
  - Latency cao → optimize embedding batch, caching
  - Vẫn không cải thiện → thử Hybrid Search (dense + BM25 keyword)
  - Câu hỏi phức tạp đa bước → cân nhắc GraphRAG hoặc Multi-Agent routing
```

> **Lưu ý:** GraphRAG và Multi-Agent là phương án dự phòng khi standard RAG không đủ tốt — không phải mặc định phải làm. Nếu score đạt ngay thì bỏ qua và tiến thẳng Phase 2.

**Definition of Done:**
- [ ] Có bộ test 20–30 câu hỏi + đáp án mẫu từ tài liệu thực
- [ ] Chạy RAGAS — có số liệu đủ 5 chỉ số Nhóm 1
- [ ] Chạy load test — có số liệu Nhóm 2
- [ ] Quyết định rõ: tiếp tục Phase 2 hay tune thêm

---

### Phase 2 — Cải tiến & Tích hợp _(Tuần 4–5)_

> **Mục tiêu:** Nâng chất lượng sản phẩm, đưa bot vào workflow thực tế của nhân viên.

**Admin Dashboard nâng cao** _(analytics cơ bản: volume / feedback / top questions đã làm ở Phase 1):_
- Mở rộng filter / drill-down theo phòng ban, theo tài liệu
- Danh sách câu hỏi bot **không trả lời được** (không tìm thấy tài liệu liên quan)

**Knowledge Gap Detection:**
- Tự động log các câu hỏi có retrieval score thấp (< 0.7)
- Admin xem được: "Nhân viên đang hỏi nhiều về X nhưng chưa có tài liệu → cần bổ sung"

**Microsoft Teams Bot Integration:**
- Nhân viên hỏi trực tiếp trong Teams, không cần mở tab mới
- Hỗ trợ DM bot hoặc mention trong channel
- Kỹ thuật: `botbuilder-python` (Microsoft Bot Framework) — cùng hệ sinh thái Azure AD đã dùng cho SSO

**Realtime 2 chiều nâng cao** _(Phase 1 đã có notify "tài liệu mới"):_
- Mở rộng loại notify: admin đăng chính sách mới, nhắc nhở cá nhân…
- Khi scale nhiều instance: backplane (NATS/Redis pub-sub) route sự kiện tới đúng instance đang giữ socket của user
- Tương tác 2 chiều: typing indicator, (xa hơn) chat nhiều người

**Definition of Done:**
- [ ] Dashboard hiển thị đủ 4 metrics: volume, feedback rate, top questions, knowledge gaps
- [ ] Admin thấy được danh sách knowledge gaps từ câu hỏi không trả lời được
- [ ] Hỏi bot ngay trong Microsoft Teams → nhận câu trả lời với nguồn tài liệu
- [ ] Notify hoạt động khi scale nhiều instance (qua backplane) + có typing indicator

---

## Tầm nhìn dài hạn _(sau 5 tuần)_

Các phase này không nằm trong scope hiện tại nhưng cho thấy sản phẩm có thể phát triển đến đâu:

| Phase | Tính năng | Giá trị |
|-------|-----------|---------|
| **Phase 3** | Onboarding flow tự động | Nhân viên mới được bot dẫn qua checklist thay vì hỏi từng người |
| **Phase 3** | REST API public | Hệ thống khác của công ty tích hợp vào chatbot |
| **Phase 4** | GraphRAG | Nâng lên knowledge graph cho câu hỏi phức tạp đa bước (Multi-agent (Orchestrator-Workers) đã triển khai sớm ở Phase 1) |
| **Phase 4** | Vietnamese embedding optimization | Cải thiện độ chính xác với tài liệu tiếng Việt |
| **Phase 4** | Auto re-index khi tài liệu cập nhật | Knowledge base luôn up-to-date |

---

## Thước đo thành công

| Milestone | Đo bằng |
|-----------|---------|
| Phase 1 Done | Upload 1 doc → hỏi → trả lời đúng với nguồn; truy cập được qua HTTPS trên GCP |
| Phase 1.5 Done | RAGAS score: Faithfulness ≥ 0.90, Answer Relevance ≥ 0.85, Context Precision ≥ 0.80, Context Recall ≥ 0.80 |
| Phase 2 Done | Dashboard hiển thị đủ 4 metrics, knowledge gaps visible, hỏi được trong Microsoft Teams |

---

## Rủi ro và cách xử lý

| Rủi ro | Xử lý |
|--------|-------|
| Phase 1 trễ → không đủ thời gian cho Phase 2 | Phase 2 độc lập, có thể làm song song sau khi core chat chạy được |
| Bot trả lời sai, team mất tin tưởng | Phase 2 làm ngay sau Phase 1, không để người dùng thấy bot bịa |
| Teams Bot integration phức tạp hơn dự kiến | Microsoft Bot Framework có document tốt; đã có Azure AD setup từ SSO nên auth dễ hơn — ước tính 2–3 ngày |
