# RAG-based Internal Q&A Chatbot
## Problem Statement & Market Analysis

> Tài liệu phân tích vấn đề và thị trường cho đề tài  
> **Xây dựng Chatbot Hỏi–Đáp dựa trên Tài liệu Nội bộ (RAG-based Q&A System)**  
> VinSmartFuture – ~4,000 nhân viên

---

# 1. Problem Statement

## 1.1 Khung phân tích vấn đề (AI Problem Statement Framework)

| **Dimension** | **Nội dung** |
|---|---|
| **Actor / Operator** | Nhân viên nội bộ VinSmartFuture (~4,000 người) cần tra cứu thông tin từ tài liệu nội bộ hàng ngày — quy trình, chính sách nhân sự, hướng dẫn kỹ thuật, policy bảo mật, tài liệu dự án. |
| **Current Workflow** | 1. Nhân viên nhớ hoặc đoán tài liệu nào có thông tin cần → 2. Mở ổ chung / SharePoint / email cũ → 3. Tìm kiếm bằng keyword (thường kém do tên file không chuẩn) → 4. Đọc lướt nhiều file, nhiều trang → 5. Nếu không tìm được → nhắn Slack hỏi đồng nghiệp hoặc HR/IT → 6. Chờ phản hồi. |
| **Bottleneck** | Bước 3–4 là cổ chai chính: tìm kiếm keyword không hiểu ngữ nghĩa, tài liệu lưu rải rác nhiều nơi, file scan không tìm được text, tên file không nhất quán, phiên bản cũ/mới lẫn lộn. Bước 5 gây mất thời gian người khác. |
| **Impact** | Mỗi nhân viên mất **15–30 phút/lần tra cứu**. Với 800 DAU × 2 lần/ngày = **~26,000 phút/ngày lãng phí** (~433 giờ/ngày toàn công ty). Thêm vào đó: rủi ro dùng sai tài liệu cũ, không có nguồn trích dẫn khi ra quyết định, HR/IT tốn thời gian trả lời câu hỏi lặp đi lặp lại. |
| **Success Metric** | • Thời gian tra cứu giảm từ 15–30 phút → **< 60 giây** cho 80% câu hỏi thông thường  <br>• Câu trả lời có dẫn nguồn tài liệu cụ thể (file, trang)  <br>• Không hallucinate: fallback rate 10–20% (từ chối khi không đủ thông tin)  <br>• Faithfulness RAGAS > 0.8, Answer Relevancy > 0.8  <br>• Latency p50 < 3 giây, p95 < 5 giây  <br>• Ingestion success rate > 95% |
| **Operational Boundary** | **Được phép:** Trả lời câu hỏi từ tài liệu đã được Admin index. Tóm tắt thông tin. Trích dẫn nguồn. Từ chối khi không đủ thông tin.  <br>**Không được phép:** Tự tổng hợp thông tin ngoài tài liệu (tuyệt đối không hallucinate). Trả lời câu hỏi về dữ liệu cá nhân nhân viên khác. Thực hiện hành động thay đổi dữ liệu (read-only).  <br>**Cần HITL:** Admin phải review và phê duyệt tài liệu trước khi index. Câu hỏi về thông tin nhạy cảm (L3–L4) phải có escalation path rõ ràng. |

---

## 1.2 Phân loại giải pháp theo ba mức

```
Rule / Script  ←——————— LLM Feature ———————→  Agent
```

| **Tiêu chí** | **Rule / Script** | **LLM Feature ← Chọn** | **Agent** |
|---|---|---|---|
| Input | Ổn định | **Biến thể vừa phải** ✅ | Thay đổi liên tục |
| Output | Logic rõ ràng | **Cần linh hoạt** ✅ | Quyết định động |
| Predictability | Cao, Compliance nặng | **Có guardrails (score threshold, fallback)** ✅ | Risk control phức tạp |
| Human Review | Tự động hoàn toàn | **Human có thể review (Langfuse, feedback)** ✅ | Cần oversight liên tục |
| Multi-tool | Không | **2 tool: Retrieval + Generation** ✅ | Nhiều bước, nhiều tool |

**→ Kết luận: LLM Feature (RAG Pipeline) là mức phù hợp cho MVP.**  
Phase 4 có thể upgrade lên Agent nếu cần xử lý câu hỏi phức tạp đa nguồn, multi-hop.

---

## 1.3 Gate Criteria – Điều kiện Go / No-Go

| **Giai đoạn** | **Go nếu...** | **No-Go nếu...** | **Trạng thái** |
|---|---|---|---|
| **Problem Scoping** | Actor (nhân viên), workflow (tra cứu tài liệu), pain (15–30 phút/lần), metric (< 60 giây, RAGAS > 0.8) đã rõ | Problem mơ hồ, mô tả solution trước problem | ✅ **Go** |
| **Data Readiness** | Có mock data (~15–20 tài liệu PDF, DOCX, Excel đa phòng ban), có ground truth Q&A 40 câu để eval | Không có nguồn dữ liệu hoặc dữ liệu quá lệch | ✅ **Go** |
| **Baseline / Model** | Baseline rõ: keyword search hiện tại mất 15–30 phút, không có citation | Chưa biết AI cần tốt hơn cái gì | ✅ **Go** |
| **Build & Eval** | Có bộ test 40 câu (Easy/Medium/Hard/Edge case), RAGAS framework, Langfuse dashboard, latency budget (p95 < 5s) | Chỉ có demo thủ công, không có reproducible eval | ✅ **Go** |
| **Deploy Controls** | Có: score threshold fallback (HITL-like), Admin approval trước khi index, Langfuse logging, rollback bằng docker image tag, owner = SA team | Không rõ ai duyệt output, ai dừng hệ thống khi sai | ✅ **Go** |

---

## 1.4 Problem – Solution Fit

```
Vấn đề cốt lõi
═══════════════
  "Nhân viên không tìm được thông tin
   đúng, nhanh, có nguồn từ tài liệu
   nội bộ bằng ngôn ngữ tự nhiên."
        │
        ▼
   RAG Pipeline giải quyết bằng cách:
   ┌────────────────────────────────────┐
   │  Embed câu hỏi → tìm chunk liên   │
   │  quan (semantic, không phải       │
   │  keyword) → LLM sinh câu trả lời  │
   │  CHỈ từ context tìm được →        │
   │  trả về kèm nguồn tài liệu        │
   └────────────────────────────────────┘
        │
        ▼
   Guardrail: score < 0.7 → Fallback
   (không gọi LLM, không hallucinate)
```

---

# 2. Phân tích thị trường (Market Analysis)

## 2.1 Landscape tổng quan

Thị trường **Enterprise Document Q&A / Internal Knowledge Chatbot** đang tăng trưởng mạnh sau khi GPT-4 ra mắt (2023). Có thể phân thành 4 nhóm:

| **Nhóm** | **Đặc điểm** | **Sản phẩm tiêu biểu** |
|---|---|---|
| **Enterprise Suite AI** | Tích hợp sâu vào bộ công cụ lớn (Microsoft 365, Google Workspace) | Microsoft Copilot, Google Gemini Workspace |
| **Specialized Knowledge Management** | Platform quản lý knowledge base + AI Q&A | Guru, Glean, Confluence AI |
| **No-code RAG Builder** | Build chatbot từ docs không cần code | Chatbase, Mendable, Botpress |
| **Open-source / Framework** | Framework tự build RAG pipeline | LlamaIndex, LangChain, Haystack |

---

## 2.2 Phân tích sản phẩm cạnh tranh

### Microsoft Copilot for Microsoft 365

| **Hạng mục** | **Chi tiết** |
|---|---|
| **Mô tả** | AI assistant tích hợp trong Word, Teams, Outlook, SharePoint. Trả lời câu hỏi dựa trên dữ liệu Microsoft 365 của tổ chức. |
| **Chức năng có** | Semantic search trên SharePoint/OneDrive; Q&A trên Teams meeting transcript; Summarize email threads; Draft document; Multi-language support (tiếng Việt ở mức cơ bản) |
| **Điểm mạnh** | Tích hợp sẵn vào hệ sinh thái Microsoft; SSO qua Azure AD; Enterprise-grade security; Data stays in Microsoft tenant |
| **Điểm yếu / Gap** | Yêu cầu Microsoft 365 E3/E5 (≈ $30–$57/user/tháng + $30 Copilot add-on); Không hoạt động tốt với tài liệu tiếng Việt scan (OCR kém); Không có score threshold rõ ràng → có thể hallucinate; Không có RAGAS evaluation built-in; Không phù hợp tổ chức không dùng Microsoft ecosystem |

---

### Google Gemini in Google Workspace

| **Hạng mục** | **Chi tiết** |
|---|---|
| **Mô tả** | Gemini AI tích hợp trong Google Docs, Drive, Gmail, Meet. Semantic search trên Google Drive content. |
| **Chức năng có** | Q&A trên Google Drive files; Summarize; Translate; Image understanding (Gemini Vision tốt); NotebookLM (chuyên dụng Q&A tài liệu) |
| **Điểm mạnh** | NotebookLM rất mạnh cho Q&A tài liệu; Gemini Vision tốt cho PDF scan tiếng Việt; Citation rõ ràng (NotebookLM có inline citation); Tiếng Việt tốt hơn Microsoft |
| **Điểm yếu / Gap** | Yêu cầu Google Workspace Business/Enterprise; Data lưu trên Google Cloud (data sovereignty vấn đề với tổ chức nhạy cảm); Không customize được pipeline; Không có observability/tracing; Không control được hallucination thủ công; NotebookLM giới hạn số tài liệu |

---

### Atlassian Intelligence (Confluence AI)

| **Hạng mục** | **Chi tiết** |
|---|---|
| **Mô tả** | AI tích hợp vào Confluence Cloud — tìm kiếm và Q&A trên knowledge base của công ty. |
| **Chức năng có** | Q&A trên Confluence pages; Auto-summarize page; Suggest related content; Rovo Search (cross-platform search) |
| **Điểm mạnh** | Rất mạnh với tổ chức đã dùng Confluence; Tích hợp sâu với Jira/Bitbucket; Access control theo Confluence space |
| **Điểm yếu / Gap** | Chỉ hoạt động với content trong Confluence (không phải PDF/Excel upload tự do); Tiếng Việt kém; Không có OCR cho file scan; Không có citation cụ thể (trang, đoạn); Đắt với SME/startup |

---

### Glean

| **Hạng mục** | **Chi tiết** |
|---|---|
| **Mô tả** | Enterprise search + AI assistant. Kết nối với 100+ nguồn dữ liệu (Slack, Drive, Confluence, GitHub, Salesforce…). |
| **Chức năng có** | Semantic search đa nguồn; Q&A với citation; Personalization theo role; Access control tự động kế thừa từ nguồn |
| **Điểm mạnh** | Rất toàn diện cho enterprise; Citation rõ ràng; Không cần upload — kết nối trực tiếp từ nguồn |
| **Điểm yếu / Gap** | Giá rất cao (≈ $20–$30/user/tháng, min 50 users); Cần IT setup connector phức tạp; Không phù hợp tổ chức không dùng cloud apps phổ biến; Tiếng Việt không được optimize; Data phải đi qua Glean server |

---

### Guru

| **Hạng mục** | **Chi tiết** |
|---|---|
| **Mô tả** | Knowledge management platform với AI Q&A. Tập trung vào "single source of truth" cho nội dung nội bộ. |
| **Chức năng có** | Tổ chức knowledge dạng card; AI Q&A trên cards; Slack integration (hỏi trong Slack); Verification workflow (content phải được verify mới dùng được) |
| **Điểm mạnh** | Verification workflow đảm bảo content luôn up-to-date; Slack-native; Tốt cho Sales enablement, CS |
| **Điểm yếu / Gap** | Cần nhập liệu thủ công vào Guru cards (không tự động từ PDF); Tiếng Việt không hỗ trợ; Không có OCR; Phụ thuộc con người để maintain content |

---

### Chatbase / Mendable (No-code RAG Builder)

| **Hạng mục** | **Chi tiết** |
|---|---|
| **Mô tả** | Platform build chatbot từ tài liệu (PDF, URL, text) mà không cần code. Phổ biến cho documentation Q&A. |
| **Chức năng có** | Upload PDF/URL/text → embed → chat widget; Integrate vào website; Basic analytics; Customizable prompt |
| **Điểm mạnh** | Setup cực nhanh (< 30 phút); Giá rẻ ($19–$99/tháng); Phù hợp SME, startup |
| **Điểm yếu / Gap** | Không hỗ trợ OCR (PDF scan không đọc được); Tiếng Việt kém (embedding model không optimize); Không có score threshold kiểm soát hallucination; Không có RAGAS/eval; Không có audit log; Không phù hợp enterprise (no SSO, no RBAC, no compliance) |

---

### FPT.AI / BKAV AI (Sản phẩm Việt Nam)

| **Hạng mục** | **Chi tiết** |
|---|---|
| **Mô tả** | Chatbot / Virtual Assistant nội địa Việt Nam, tập trung customer service hơn internal knowledge. |
| **Chức năng có** | FAQ chatbot; Voice bot; Tiếng Việt NLP tốt; On-premise deployment tùy chọn |
| **Điểm mạnh** | Tiếng Việt tốt nhất trong thị trường nội địa; Hỗ trợ triển khai on-premise; Phù hợp compliance Việt Nam; Không gửi data ra nước ngoài |
| **Điểm yếu / Gap** | Là FAQ/rule-based bot chứ không phải RAG (không hiểu ngữ cảnh); Không có semantic search trên tài liệu tự do; Không có citation; Tốn kém customization; Không open-source → vendor lock-in nặng |

---

## 2.3 So sánh Feature Matrix

| **Tính năng** | MS Copilot | Google Gemini | Glean | Chatbase | FPT.AI | **RAG Chatbot (đề tài này)** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Upload PDF/DOCX/Excel tự do | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ |
| OCR cho PDF scan | ⚠️ | ✅ | ❌ | ❌ | ❌ | ✅ (Gemini Vision API) |
| Tiếng Việt chất lượng cao | ⚠️ | ✅ | ❌ | ❌ | ✅ | ✅ |
| Citation cụ thể (file, trang) | ⚠️ | ✅ | ✅ | ⚠️ | ❌ | ✅ |
| Hallucination control (score threshold) | ❌ | ❌ | ❌ | ❌ | N/A | ✅ |
| RAGAS / Eval framework | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| LLM Observability (trace, latency, cost) | ⚠️ | ⚠️ | ⚠️ | ❌ | ❌ | ✅ (Langfuse) |
| RBAC (Admin / End User) | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Multi-turn conversation | ✅ | ✅ | ✅ | ⚠️ | ❌ | ✅ (3 turns) |
| On-premise / Data sovereignty | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ (Phase 3) |
| Audit log | ✅ | ✅ | ✅ | ❌ | ⚠️ | ✅ |
| Giá phù hợp SME/startup Việt Nam | ❌ | ⚠️ | ❌ | ✅ | ⚠️ | ✅ (self-hosted) |
| Open-source / tự control | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

*✅ = Có đầy đủ | ⚠️ = Có nhưng hạn chế | ❌ = Không có*

---

## 2.4 Khoảng trống thị trường (Market Gaps)

Dựa trên phân tích trên, **5 gap chính** mà các sản phẩm hiện tại chưa giải quyết tốt cho doanh nghiệp Việt Nam quy mô vừa:

### Gap 1 – OCR tiếng Việt cho PDF scan
Đa số sản phẩm (Chatbase, Glean, Atlassian AI) không có OCR. Microsoft OCR tiếng Việt không chính xác với tài liệu có nhiều dấu. Trong khi doanh nghiệp Việt Nam có lượng lớn tài liệu scan (hợp đồng, quyết định, biên bản họp).

**→ Giải pháp: Gemini Vision API, chất lượng OCR cao, hỗ trợ tốt tiếng Việt và bảng/layout phức tạp.**

### Gap 2 – Hallucination control có thể cấu hình
Không sản phẩm nào cho phép tổ chức tự set ngưỡng confidence và enforce "không trả lời nếu không đủ thông tin." Điều này nguy hiểm trong môi trường enterprise (nhân viên tin vào câu trả lời sai).

**→ Giải pháp: Score threshold 0.7, fallback cứng, không gọi LLM khi không đủ context.**

### Gap 3 – Observability và đánh giá chất lượng RAG
Không sản phẩm nào cung cấp RAGAS evaluation hoặc dashboard trace chi tiết để tổ chức tự đo chất lượng. Tổ chức mua xong phải tin tưởng "black box."

**→ Giải pháp: RAGAS evaluation pipeline + Langfuse tracing dashboard.**

### Gap 4 – Giá phù hợp + không vendor lock-in
Sản phẩm enterprise (Copilot, Glean) giá $20–$60/user/tháng → với 4,000 nhân viên = $80k–$240k/tháng. Quá đắt cho tổ chức Việt Nam không phải tập đoàn lớn.

**→ Giải pháp: Self-hosted, open-source stack (FastAPI + Qdrant + PostgreSQL), chỉ trả tiền API (OpenAI + Gemini Vision API).**

### Gap 5 – Data residency tại Việt Nam / khu vực
Tất cả sản phẩm SaaS gửi data ra ngoài (US/EU). Với tổ chức nhạy cảm dữ liệu (y tế, tài chính, chính phủ), đây là rào cản compliance.

Nếu cái đơn giản này render được thì lỗi nằm ở syntax phức tạp trong 3 diagrams. Nếu vẫn không render thì extension chưa active đúng — thử restart VSCode.

Bạn thử và cho tôi biết kết quả nhé.

**→ Giải pháp: Phase 3 self-hosted toàn bộ trên GCP Singapore (asia-southeast1), Langfuse self-hosted.**

---

## 2.5 Định vị sản phẩm (Positioning)

```
                    Tính năng AI / RAG
                         │ Cao
                         │
          Google     ●   │   ● Glean
          Gemini         │
                         │
  ─────────────────────────────────────────
  Giá cao                │              Giá thấp
  Vendor lock-in         │              Tự kiểm soát
                         │
                         │         ● RAG Chatbot
          MS         ●   │           (đề tài này)
          Copilot        │         ● Chatbase
                         │
                         │ Thấp
```

**RAG Chatbot (đề tài này) định vị tại:**
- **Góc phải-trên**: Tính năng AI/RAG đầy đủ + Giá thấp + Tự kiểm soát
- Phù hợp: Doanh nghiệp Việt Nam quy mô 500–5,000 nhân viên, không dùng Microsoft/Google Workspace toàn phần, hoặc cần data sovereignty.

---

# 3. Why RAG? – So sánh các kỹ thuật retrieval

| **Kỹ thuật** | **Cách hoạt động** | **Ưu điểm** | **Nhược điểm** | **Phù hợp khi nào** |
|---|---|---|---|---|
| **Keyword Search** (hiện tại) | Tìm từ khóa trong tên file / full-text index | Đơn giản, nhanh | Không hiểu ngữ nghĩa ("nghỉ phép" ≠ "leave policy"), không xử lý PDF scan | Data nhỏ, query đơn giản |
| **Full-text Search (Elasticsearch)** | Inverted index + BM25 scoring | Tốt với text query, có highlight | Vẫn là keyword-based, không hiểu đồng nghĩa, typo nhạy cảm | Log search, product catalog |
| **Fine-tuned LLM** | Train LLM trên data riêng | Trả lời tự nhiên, không cần retrieval | Tốn kém ($$$), data cũ ngay sau training, hallucinate | Domain cực chuyên biệt, data ổn định |
| **RAG (đề tài này)** | Embed → Semantic Search → LLM với context | Hiểu ngữ nghĩa, citation rõ ràng, data cập nhật real-time, kiểm soát hallucination | Cần tuning chunking/threshold, latency cao hơn keyword | **Internal knowledge base → phù hợp nhất** |
| **GraphRAG** | Knowledge graph + RAG | Xử lý quan hệ phức tạp, multi-hop reasoning | Rất phức tạp, khó scale | Ontology, câu hỏi đa thực thể |

**→ RAG là lựa chọn tối ưu cho bài toán này.**

---

# 4. Tóm tắt

| **Hạng mục** | **Nội dung** |
|---|---|
| **Vấn đề cốt lõi** | Nhân viên mất 15–30 phút/lần tra cứu thông tin từ tài liệu nội bộ, không có citation, không scale |
| **Giải pháp** | RAG Pipeline: Semantic search + LLM + Score threshold fallback |
| **Mức độ giải pháp** | LLM Feature (không phải Rule, chưa cần Agent trong MVP) |
| **Gate: Go** | Tất cả 5 gate đều Go – problem rõ, data sẵn, baseline xác lập, eval framework có, deploy controls rõ |
| **Thị trường** | Sản phẩm enterprise (Copilot, Glean) đắt và không phù hợp doanh nghiệp Việt Nam; No-code (Chatbase) thiếu OCR, eval, hallucination control |
| **Khoảng trống** | OCR tiếng Việt + Hallucination control + RAGAS eval + Giá thấp + Data residency |
| **Định vị** | Self-hosted RAG: full-featured, low-cost, tự kiểm soát – phù hợp SME Việt Nam 500–5,000 nhân viên |
