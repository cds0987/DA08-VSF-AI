# Domain Model — RAG Internal Chatbot

> Tài liệu **nền nghiệp vụ** (WHAT + WHY). Nó đứng **trước** các tài liệu kỹ thuật
> ([clean-architecture.md](../2-architecture/clean-architecture.md), [contracts.md](../3-technical/contracts.md),
> [data-schema.md](../3-technical/data-schema.md), [team-ownership.md](../delivery/team-ownership.md)) — vốn trả lời **HOW**.
>
> Quy tắc đọc: mọi quyết định kỹ thuật (HOW) phải truy ngược được về một **quy tắc nghiệp vụ (WHY)**,
> và mọi quy tắc nghiệp vụ phải truy ngược được về một **định nghĩa domain (WHAT)**.
> Nếu một dòng code không truy ngược được tới đây → đó là dấu hiệu thiết kế đang đoán.

---

## 0. Cách dùng tài liệu này

| Tầng | Trả lời câu hỏi | Nằm ở |
|---|---|---|
| **WHAT** | Chúng ta đang giải bài toán nghiệp vụ gì? "Đúng" nghĩa là gì? | Mục 1–4 (file này) |
| **WHY** | Vì sao hệ thống được phép / không được phép hành xử thế? | Mục 5–6 (file này) |
| **HOW** | Xây bằng gì, ở đâu, ai làm? | Các file kỹ thuật khác |

Tài liệu này **không chứa code, framework, hay LLM**. Đó là chủ ý.

---

# PHẦN I — WHAT

## 1. Domain là gì

### 1.1. Bài toán thật

Chatbot **không phải là domain**. Nó là *kênh phân phối* cho domain bên dưới. Phép thử:
*"Nếu bỏ chatbot đi, nghiệp vụ này còn tồn tại không?"* — Có. Nhân viên vẫn hỏi HR về phép năm,
vẫn hỏi IT cách reset VPN. Đó mới là domain.

> **Domain cốt lõi:** Giúp nhân viên lấy được **câu trả lời đúng, đúng phạm vi áp dụng cho chính họ**,
> từ kho tri thức/chính sách nội bộ phân tán.

Điểm tinh tế nằm ở cụm **"đúng phạm vi áp dụng cho chính họ"**. Vì chính sách khác nhau theo
**văn phòng** và **cấp bậc**, nên cùng một câu hỏi có **nhiều câu trả lời đúng khác nhau**.

### 1.2. Sự thật nền tảng (đừng bao giờ quên)

> **Một câu hỏi → nhiều câu trả lời đúng, tùy người hỏi.**
>
> "Tôi được bao nhiêu ngày phép?" — nhân viên Hà Nội cấp nhân viên và quản lý HCM có
> *câu trả lời đúng khác nhau*. Đây **không** phải bài toán "tìm tài liệu khớp nhất",
> mà là bài toán **"tìm tài liệu áp dụng cho đúng người đang hỏi"**.

Đây là thứ phân biệt dự án này với một con chatbot search tầm thường. Nếu hệ thống trả
"một câu trả lời cho tất cả mọi người" → nó đã sai về bản chất, dù RAG có chính xác đến đâu.

### 1.3. Phân loại domain — để biết dồn sức vào đâu

| Loại | Phần nào | Vì sao |
|---|---|---|
| **Core Domain** ⭐ | Logic "policy nào áp cho ai" (theo office + level + thời gian) | Know-how riêng của công ty, không mua ngoài được |
| **Supporting** | Quản lý nguồn tài liệu, phân loại, thẩm quyền, hiệu lực | Cần thiết nhưng không tạo lợi thế |
| **Generic** | Search, embedding, LLM, chat UI | Mua/dùng sẵn — **đừng tự xây, đừng dồn sức** |

> ⚠️ **Cảnh báo đầu tư:** sức nặng phải đặt vào **policy scoping** (Core), không phải vào
> RAG pipeline (Generic). RAG tốt mà scoping sai = sản phẩm sai.

### 1.4. Tổ chức công ty (ngữ cảnh cố định)

- **Quy mô:** ~4000 nhân viên.
- **Văn phòng:** **Hà Nội**, **Hồ Chí Minh** *(chỉ 2 văn phòng)*.
- **Phòng ban:** HR, IT, Finance, Legal, Operations.
- **Chính sách:** có thể khác nhau theo **văn phòng** và **cấp bậc**.
- **Hệ thống tri thức hiện tại:** Confluence, Slack, Microsoft Teams.

---

## 2. Ubiquitous Language (Ngôn ngữ chung)

> Không có **một** từ điển cho cả công ty. Có một phần nhỏ dùng chung (**Shared Kernel**),
> còn lại mỗi Bounded Context có từ điển riêng — và **cùng một từ được phép mang nghĩa khác nhau**.

### 2.1. Shared Kernel — dùng chung toàn hệ thống

| Thuật ngữ | Định nghĩa thống nhất |
|---|---|
| **Employee** | Một cá nhân có danh tính trong tổ chức, định danh duy nhất |
| **Office** | Văn phòng vật lý: Hà Nội / HCM |
| **Department** | Phòng ban: HR / IT / Finance / Legal / Operations |
| **Question** | Một lượt hỏi của nhân viên bằng ngôn ngữ tự nhiên |
| **Answer** | Phản hồi hệ thống trả cho một Question |
| **Source Document** | Tài liệu gốc làm căn cứ cho câu trả lời |
| **Citation** | Tham chiếu từ Answer về Source Document cụ thể (để truy vết) |

> Lưu ý: `Employee` trong Shared Kernel **chỉ là danh tính tối thiểu** (ai). Các thuộc tính
> phong phú (cấp lương, quyền hệ thống...) thuộc về từng context riêng, không dùng chung.

### 2.2. Từ riêng theo Bounded Context (trích yếu)

**Identity & Access:** `Access Profile` (hồ sơ quyết định "thấy được gì"), `Organizational Level`
(cấp tổ chức để scope tài liệu), `Scope of Applicability` (tập điều kiện tài liệu áp dụng cho ai),
`Employment Status` (Active / OnLeave / Terminated).

**HR Knowledge:** `Policy` (quy định nhân sự), `Entitlement` (quyền lợi cụ thể một người được hưởng),
`Effective Period` (khoảng hiệu lực), `Sensitive Topic` (chủ đề nhạy cảm phải chuyển người thật).

**IT Support:** `Ticket`, `Runbook`/`Procedure`, `SLA`, `Escalation`.

**Finance/Legal:** `Confidential Document`, `Legal Commitment` (phát ngôn ràng buộc pháp lý),
`Restricted Topic` (chủ đề bot bị cấm tự trả lời), `Audit Entry`.

**Knowledge Ingestion:** `Knowledge Source` (Confluence/Slack/Teams), `Source of Truth`
(tài liệu chính thức), `Document Owner` (người chịu trách nhiệm tính đúng), `Freshness`.

**Conversation/Delivery:** `Conversation`, `Turn`, `Channel`, `Handoff` (chuyển cho người thật).

### 2.3. ⚠️ Bảng "TỪ NGUY HIỂM" — đa nghĩa xuyên context

Đây là nguồn gốc của ~80% bug nghiệp vụ. **Dán lên tường khi thiết kế.**

| Từ | Identity | HR | IT | Finance | → Quy ước |
|---|---|---|---|---|---|
| **Level** | Cấp tổ chức | Cấp lương | Cấp quyền hệ thống | Cấp duyệt chi | **Không bao giờ dùng "Level" trần** — luôn gắn tiền tố: `OrgLevel`, `SalaryBand`, `AccessLevel`, `ApprovalTier` |
| **Policy** | — | Quy định nhân sự | Quy định bảo mật | Quy định tuân thủ | Luôn gắn ngữ cảnh: `HrPolicy`, `ItPolicy`... |
| **Approval** | — | Duyệt đơn HR | Cấp quyền | Duyệt chi tiêu | Mỗi context một workflow riêng |
| **Active** | Còn quyền truy cập | Còn hợp đồng | Còn account | Còn trên payroll | Định nghĩa `EmploymentStatus` ở Identity, các context khác *tham chiếu* |
| **Request** | — | Đơn từ | Ticket | Đề nghị chi | Mỗi context một tên riêng |

---

## 3. Bounded Contexts

Tiêu chí chia: mỗi context có **một ngôn ngữ thống nhất riêng, một domain expert riêng,
một bộ quy tắc nghiệp vụ riêng**. Khi một từ đổi nghĩa → đó là ranh giới context.

> ⚠️ **Lưu ý chiến lược:** Bounded Context ≠ microservice. Ranh giới *service*
> (user/chat/rag) là cách chia tải kỹ thuật. Ranh giới *context* dưới đây là cách chia
> theo **nghĩa nghiệp vụ**. Một service có thể phục vụ nhiều context, hoặc ngược lại.

```
┌─────────────────────────────────────────────────────────┐
│              IDENTITY & ACCESS CONTEXT (lõi)             │
│         "Người hỏi là ai, được phép thấy GÌ"             │
│   Ngôn ngữ: Employee, Office, OrgLevel, Scope            │
└─────────────────────────────────────────────────────────┘
        ▲ cung cấp danh tính + scope cho mọi context dưới
        │
┌───────────────┬───────────────┬──────────────┬──────────┐
│ HR KNOWLEDGE  │  IT SUPPORT   │ FINANCE/LEGAL │ GENERAL/ │
│  (core)       │               │ (rủi ro cao)  │ FACILIT. │
└───────────────┴───────────────┴──────────────┴──────────┘
        │ tất cả đọc từ ↓
┌─────────────────────────────────────────────────────────┐
│           KNOWLEDGE INGESTION CONTEXT (supporting)       │
│  "Tài liệu vào từ đâu, ai chịu trách nhiệm, còn hiệu lực"│
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│        CONVERSATION / DELIVERY CONTEXT (generic)         │
│   Chatbot UI nằm ĐÂY — cố tình "mù" về nghiệp vụ          │
└─────────────────────────────────────────────────────────┘
```

### Ranh giới giữa các context

| Ranh giới | Phân tách bởi |
|---|---|
| HR ↔ IT ↔ Finance | Ngôn ngữ khác nhau (xem bảng "từ nguy hiểm") + domain expert khác nhau |
| Identity ↔ Knowledge contexts | Identity *quyết định scope*; Knowledge *dùng scope để lọc*. Logic "ai thấy gì" tập trung ở Identity, không rải rác |
| Ingestion ↔ Knowledge | Ingestion lo *nguồn & độ tươi*; Knowledge lo *diễn giải*. Đổi nguồn không đụng logic nghiệp vụ |
| Conversation ↔ tất cả | Conversation chỉ lo *kênh & hội thoại*, mù về nội dung nghiệp vụ |

### Team chịu trách nhiệm (Conway's Law)

| Context | Team owner | Domain expert đi kèm |
|---|---|---|
| Identity & Access ⭐ | Platform/Core team | HR (cơ cấu tổ chức) + Legal (quyền xem) |
| HR Knowledge ⭐ | Core team + HR Policy Owner | HR |
| IT Support | IT team + Helpdesk Lead | IT |
| Finance/Legal | Compliance team | Legal / Finance |
| Knowledge Ingestion | Platform team | Confluence admins |
| Conversation | Product team | UX (không cần domain expert) |

### 3.5. Context Map — quan hệ tích hợp giữa các context

> Bounded Context không sống cô lập. Context Map mô tả **ai phụ thuộc ai** và **mỗi quan hệ
> được bảo vệ thế nào**. Hai thuật ngữ then chốt:
> - **Upstream (U)** = bên *cung cấp*, áp đặt mô hình của mình lên bên kia.
> - **Downstream (D)** = bên *phụ thuộc*, phải chịu mô hình của upstream.
> - **ACL (Anti-Corruption Layer)** = lớp dịch thuật, ngăn mô hình bẩn của upstream "rò" vào
>   và làm hỏng ngôn ngữ của downstream.

```
                    ┌──────────────────────────┐
   (nguồn ngoài)    │  IDENTITY & ACCESS  (U)   │
   HRIS / AD ──ACL──▶│  nguồn sự thật về:        │
                    │  ai, office, OrgLevel,    │
                    │  Employment Status        │
                    └──────────┬───────────────┘
                               │ U (cung cấp Access Profile + Scope)
            ┌──────────────┬───┴────────┬───────────────┐
            ▼ D            ▼ D          ▼ D              ▼ D
      ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌──────────┐
      │   HR     │  │   IT     │  │ FINANCE/   │  │ GENERAL  │
      │ KNOWLEDGE│  │ SUPPORT  │  │  LEGAL     │  │          │
      └────┬─────┘  └────┬─────┘  └─────┬──────┘  └────┬─────┘
           │ D           │ D            │ D            │ D
           └─────────────┴──────┬───────┴─────────────┘
                                ▼ U (cung cấp tài liệu "đủ điều kiện")
                    ┌──────────────────────────┐
                    │  KNOWLEDGE INGESTION (U)  │
   Confluence ─ACL─▶│  Source of Truth, Owner,  │
   Slack/Teams ─ACL▶│  hiệu lực, phân loại      │
                    └──────────────────────────┘

      ┌──────────────────────────────────────────────┐
      │  CONVERSATION / DELIVERY  (D với tất cả)      │
      │  điều phối hỏi-đáp + Handoff, mù về nghiệp vụ │
      └──────────────────────────────────────────────┘
```

#### Bảng quan hệ (đọc kèm sơ đồ)

| Quan hệ | Kiểu | **Vì sao đặt như vậy** |
|---|---|---|
| Identity → HR / IT / Finance / General | **U → D** (Customer–Supplier) | Identity là **nguồn sự thật duy nhất** về "ai + scope". Mọi context nghiệp vụ *phụ thuộc* nó, không tự định nghĩa lại office/level. Tập trung hoá để tránh rò rỉ phạm vi (rủi ro #1). |
| Ingestion → HR / IT / Finance / General | **U → D** (Customer–Supplier) | Ingestion cung cấp *tài liệu đủ điều kiện* (có owner, còn hiệu lực, là Source of Truth). Context nghiệp vụ chỉ *diễn giải*, không lo nguồn. |
| **HRIS/AD → Identity** | **ACL bắt buộc** | Hệ thống nhân sự ngoài có mô hình riêng (mã nhân viên, cơ cấu phòng ban lạ). ACL dịch sang ngôn ngữ Identity, **không để cấu trúc ngoài rò vào** Core Domain. |
| **Confluence/Slack/Teams → Ingestion** | **ACL bắt buộc** | Mỗi nguồn có định dạng & khái niệm "tài liệu" khác nhau; Slack còn lẫn chính thức với phi chính thức. ACL chuẩn hoá + gắn nhãn Source of Truth trước khi vào trong. |
| Conversation → mọi context nghiệp vụ | **D** (Conformist) | Conversation *cố tình tuân theo* mô hình của context nghiệp vụ, không áp mô hình ngược lại. Nó mù về nghiệp vụ — đây là chủ ý, không phải thiếu sót. |
| HR ↔ IT ↔ Finance | **Separate Ways** (tách hẳn) | Không chia sẻ mô hình. "Policy" mỗi bên một nghĩa (xem bảng "từ nguy hiểm"). Cố hợp nhất = tạo bug nghiệp vụ. |

#### Ba điểm rút ra (định hướng kiến trúc về sau)

1. **Identity & Access là upstream của tất cả** → nó phải được thiết kế & freeze *trước*. Nếu nó
   sai, mọi context dưới đều rò rỉ phạm vi. Đây là lý do nó là Core và được team mạnh nhất giữ.
2. **Hai nơi BẮT BUỘC có ACL** là hai cửa nối với thế giới ngoài: *HRIS/AD → Identity* và
   *Confluence/Slack/Teams → Ingestion*. Mọi "bẩn" của hệ thống ngoài phải dừng ở đây, không rò
   vào Core.
3. **Conversation là downstream thuần** (Conformist) → giữ nó "ngu" về nghiệp vụ là *đúng thiết kế*.
   Mọi cám dỗ nhét logic nghiệp vụ vào tầng chat đều là rò rỉ ranh giới.

---

## 4. Building Blocks theo context

> Mô tả bằng ngôn ngữ tự nhiên. **Entity** = có định danh & vòng đời. **Value Object (VO)** =
> bất biến, so sánh bằng giá trị. **Aggregate** = cụm có một root bảo vệ quy tắc bất biến.

### 4.1. Identity & Access ⭐ (Core)
- **Entities:** `Employee`, `AccessProfile`
- **VO:** `Office`, `Department`, `OrgLevel`, `EmploymentStatus`, `ScopeOfApplicability` *(VO quan trọng nhất hệ thống)*, `VisibilityDecision`
- **Aggregate trung tâm:** `AccessProfile` — cổng duy nhất quyết định "người này thấy được gì"
- **Use case đinh:** đánh giá "Access Profile X có thoả Scope của tài liệu Y không?"

### 4.2. HR Knowledge ⭐ (Core)
- **Entities:** `Policy`, `EntitlementRule`
- **VO:** `EffectivePeriod`, `EntitlementValue`, `PolicyCondition` (áp cho office/level nào), `SensitiveTopic`
- **Aggregate trung tâm:** `Policy` — bảo vệ "không trả policy hết hạn hoặc sai điều kiện"
- **Use case đinh:** tìm policy *áp dụng cho chính người hỏi* (scope + thời gian)

### 4.3. IT Support
- **Entities:** `Ticket`, `Runbook`
- **VO:** `TicketStatus`, `Priority`, `SLA`, `ProcedureStep`
- **Aggregate trung tâm:** `Ticket` — bot không tự hành động, yêu cầu nhạy cảm phải thành Ticket
- **Use case đinh:** phân loại "tự trả lời" vs "tạo Ticket / escalate"

### 4.4. Finance/Legal (rủi ro cao)
- **Entities:** `ComplianceRule`, `RestrictedTopicRegistry`
- **VO:** `ConfidentialityLevel`, `Disclaimer`, `RestrictedTopic`, `AuditEntry`
- **Aggregate trung tâm:** `ComplianceGuard` — chốt chặn cuối "được trả lời nội dung này không"
- **Use case đinh:** gate chủ đề restricted / confidential trước khi trả lời

### 4.5. Knowledge Ingestion (Supporting)
- **Entities:** `SourceDocument`, `IngestionJob`
- **VO:** `KnowledgeSource`, `DocumentClassification`, `Freshness`, `SourceOfTruthFlag`, `DocumentOwner`
- **Aggregate trung tâm:** `SourceDocument` — chỉ tài liệu có owner + còn hiệu lực + là Source of Truth mới "đủ điều kiện phục vụ"
- **Use case đinh:** cung cấp tập tài liệu "đủ điều kiện" cho các context nghiệp vụ

### 4.6. Conversation/Delivery (Generic)
- **Entities:** `Conversation`, `Turn`
- **VO:** `Channel`, `SessionId`, `HandoffRequest`
- **Aggregate trung tâm:** `Conversation` — gắn danh tính, không rò lịch sử chéo, điều phối Handoff
- **Use case đinh:** định tuyến câu hỏi + thực hiện Handoff sang người thật

---

# PHẦN II — WHY

## 5. Quy tắc nghiệp vụ (kèm LÝ DO)

> 🔴 **CỨNG** = bất biến, vi phạm là hỏng, không được cấu hình tắt.
> 🟡 **MỀM** = cấu hình được theo office/department/thời điểm.
> Cột **Vì sao** là phần quan trọng nhất — nó cho dev biết *khi nào tuyệt đối không được vi phạm*.

### 5.1. Bốn invariant xương sống (xuyên mọi context)

| Quy tắc | Loại | **Vì sao (WHY)** |
|---|---|---|
| **Scope-before-content** — lọc tài liệu theo scope người hỏi *trước khi* dùng nội dung để trả lời | 🔴 | Vì rò rỉ sai phạm vi là **rủi ro số 1** (xem 6.1). Lọc sau khi LLM đã thấy = đã rò. |
| **Grounding bắt buộc** — câu trả lời về policy/quyền lợi phải dựa trên Source of Truth và phải trích nguồn; không nguồn → "tôi không biết" | 🔴 | Vì câu trả lời có thể bị chụp màn hình làm bằng chứng. Không nguồn = công ty "cam kết" điều không có thật. |
| **Quyền từ chối an toàn** — confidence thấp hoặc chủ đề nhạy cảm → từ chối + chuyển người thật, không đoán | 🔴 | Vì sai tự tin **nguy hiểm hơn** "không biết": nó khiến nhân viên hành động sai → tranh chấp. |
| **Audit & Citation** — mọi câu trả lời về quyền lợi/pháp lý phải ghi: ai hỏi, bot trả gì, dựa nguồn nào, lúc nào | 🔴 | Vì khi có tranh chấp pháp lý, công ty **phải chứng minh được** bot đã nói gì dựa trên đâu. Đây là phòng vệ, không phải debug. |

### 5.2. Identity & Access
| # | Quy tắc | Loại | Vì sao |
|---|---|---|---|
| IA-1 | Mọi câu hỏi phải gắn danh tính xác định trước khi xử lý | 🔴 | Không biết người hỏi là ai → không thể xác định scope đúng |
| IA-2 | Default khi không xác định được scope = **deny** | 🔴 | An toàn mặc định: thà chặn nhầm còn hơn rò nhầm |
| IA-3 | Nhân viên `Terminated` bị từ chối toàn bộ truy cập | 🔴 | Người đã nghỉ việc không còn quyền với tri thức nội bộ |
| IA-4 | Ngưỡng level để thấy một loại tài liệu | 🟡 | Khác nhau theo loại tài liệu, cần cấu hình |

### 5.3. HR Knowledge
| # | Quy tắc | Loại | Vì sao |
|---|---|---|---|
| HR-1 | Trả lời về Entitlement phải dựa trên policy *còn hiệu lực với chính người đó* | 🔴 | Policy thay đổi theo thời gian; trả theo bản hết hạn = ra quyết định sai |
| HR-2 | Không trộn nhiều policy mâu thuẫn mà không nêu rõ điều kiện áp dụng | 🔴 | Vì cùng câu hỏi có nhiều đáp án đúng theo office/level — gộp lại sẽ sai cho mọi người |
| HR-3 | Không tiết lộ quyền lợi/lương của nhân viên *khác* | 🔴 | Bảo mật nội bộ + công bằng + có thể vi phạm luật lao động |
| HR-4 | Chủ đề nhạy cảm (sa thải, kỷ luật, tranh chấp) → không tự trả lời, chuyển người thật | 🔴 | Có những câu hỏi mà tự động hóa là sai về đạo đức/pháp lý |
| HR-5 | Số ngày phép, mức phụ cấp theo office/level | 🟡 | Đây chính là phần "khác theo văn phòng và cấp bậc" |

### 5.4. IT Support
| # | Quy tắc | Loại | Vì sao |
|---|---|---|---|
| IT-1 | Hướng dẫn lấy từ Runbook là Source of Truth, không bịa bước | 🔴 | Bước sai có thể làm hỏng hệ thống của nhân viên |
| IT-2 | Bot không tự thực hiện hành động thay đổi hệ thống — chỉ hướng dẫn hoặc tạo Ticket | 🔴 | Tự ý cấp quyền/reset = lỗ hổng bảo mật |
| IT-3 | Yêu cầu bảo mật/cấp quyền nhạy cảm → bắt buộc tạo Ticket cho người thật | 🔴 | Cần con người xác minh danh tính & thẩm quyền |

### 5.5. Finance/Legal
| # | Quy tắc | Loại | Vì sao |
|---|---|---|---|
| FL-1 | Không bao giờ tiết lộ nội dung Confidential Document (hợp đồng, NDA, lương cá nhân) | 🔴 | Vi phạm hợp đồng/luật bảo mật |
| FL-2 | Không tạo Legal Commitment thay công ty; phải kèm disclaimer | 🔴 | Phát ngôn của bot có thể bị coi là cam kết chính thức |
| FL-3 | Restricted Topic → từ chối + chuyển người thật, tuyệt đối không đoán | 🔴 | Rủi ro pháp lý cao nhất; sai một câu có thể thành kiện tụng |

### 5.6. Knowledge Ingestion
| # | Quy tắc | Loại | Vì sao |
|---|---|---|---|
| KI-1 | Chỉ tài liệu đánh dấu Source of Truth mới dùng để trả lời về policy/quyền lợi | 🔴 | Thảo luận Slack ≠ chính sách chính thức |
| KI-2 | Mỗi tài liệu phải có Document Owner trước khi được dùng | 🔴 | Không có người chịu trách nhiệm → kho tri thức thối dần không ai biết |
| KI-3 | Tài liệu hết hiệu lực bị loại khỏi nguồn trả lời | 🔴 | Tài liệu cũ trả lời như thể còn đúng = nguy hiểm im lặng |
| KI-4 | Thảo luận Slack/Teams không tự động là Source of Truth | 🔴 | "Ai nói" quan trọng ngang "nói gì" |

### 5.7. Conversation/Delivery
| # | Quy tắc | Loại | Vì sao |
|---|---|---|---|
| CV-1 | Mỗi hội thoại phải gắn danh tính xác thực (không ẩn danh) | 🔴 | Không có danh tính → không scope được, không audit được |
| CV-2 | Khi context nghiệp vụ yêu cầu Escalation → phải Handoff, không nuốt yêu cầu | 🔴 | Bot không bao giờ là điểm cuối cho câu hỏi nhạy cảm |
| CV-3 | Lịch sử hội thoại không vượt ranh giới quyền (không đọc session người khác) | 🔴 | Rò rỉ chéo dữ liệu cá nhân |

---

## 6. Rủi ro nghiệp vụ (xếp theo mức nghiêm trọng)

| # | Rủi ro | Hậu quả | **Vì sao đáng sợ** |
|---|---|---|---|
| 🔴 1 | **Rò rỉ sai phạm vi** — thấy policy/lương của level cao hơn hoặc office khác | Vi phạm bảo mật, mất công bằng, có thể vi phạm luật | Đây là **lỗi im lặng** — không ai báo nhưng đã rò. Phải thiết kế quanh nó *từ đầu*, không vá sau. |
| 🔴 2 | **Trả lời sai về quyền lợi → nhân viên hành động sai** | Vd bot nói "18 ngày phép" (thật ra 12) → xin nghỉ → tranh chấp | Câu trả lời *tự tin nhưng sai* nguy hiểm hơn "không biết" |
| 🔴 3 | **Bịa câu trả lời cho câu hỏi pháp lý/tài chính** | Công ty bị coi là đã cam kết điều không có | Có thể bị chụp màn hình làm bằng chứng |
| 🟠 4 | **Trả lời theo tài liệu hết hiệu lực** | Dùng policy cũ → quyết định sai | Confluence đầy tài liệu outdated không ai xóa |
| 🟠 5 | **Không escalate khi cần người thật** | Nhân viên khủng hoảng (vd tố cáo quấy rối) gặp con bot | Vừa vô cảm vừa rủi ro pháp lý/đạo đức |

> **Nguyên tắc thiết kế số 1 rút ra từ bảng này:** Rủi ro #1 (rò rỉ phạm vi) liên quan trực tiếp
> đến Core Domain "policy nào áp cho ai". **Không thể thêm bảo mật sau** — nó phải là invariant
> *Scope-before-content* ngay từ dòng thiết kế đầu tiên.

---

# PHẦN III — Điều CHƯA biết (phải hỏi domain expert)

> Mục này tồn tại vì một tài liệu nghiệp vụ trung thực phải **thừa nhận điều mình chưa biết**,
> thay vì giả vờ mọi thứ đã chắc chắn. Đây là danh sách câu hỏi mang đi họp.

### Hỏi HR Policy Owner
- Cùng câu hỏi "tôi có bao nhiêu ngày phép", có bao nhiêu đáp án khác nhau? Khác theo office, level, loại hợp đồng, hay thâm niên?
- Khi một chính sách thay đổi, bản cũ còn hiệu lực với ai không? (vd người ký hợp đồng trước mốc áp luật cũ)
- Thông tin nào nhân viên **không được biết** về policy của nhau? (vd thang lương theo level)

### Hỏi Legal / Compliance
- Loại câu hỏi nào nếu trả lời sai sẽ tạo **nghĩa vụ pháp lý** cho công ty?
- Câu trả lời của bot có được coi là **cam kết chính thức** không? → quyết định disclaimer.
- Danh sách **Restricted Topic** tối thiểu (sa thải, tranh chấp, tư vấn pháp lý...) là gì?

### Hỏi IT Helpdesk Lead
- Top 20 câu hỏi lặp lại nhiều nhất? → đây là MVP scope thật.
- Câu nào tự trả lời được, câu nào **bắt buộc** phải có người thật?

### Hỏi Confluence/Knowledge Admin
- Tài liệu nào là **Source of Truth** chính thức? Phân biệt thế nào với thảo luận Slack?
- Ai là **Document Owner** chịu trách nhiệm từng nhóm tài liệu?
- Tài liệu nào đang **outdated** nhưng chưa ai xóa?

### Câu hỏi xuyên suốt cho mọi expert
- *Khi nào câu trả lời "tôi không biết" là **đúng và an toàn hơn** một câu trả lời đoán?*
  → câu này định nghĩa nguyên tắc nền tảng của toàn hệ thống.

---

## Phụ lục — Trật tự WHAT → WHY → HOW

Tài liệu này (WHAT + WHY) đứng **trước** các tài liệu kỹ thuật (HOW). Mỗi tầng là *lý do tồn tại*
của tầng dưới:

```
WHAT  → "câu trả lời đúng" tùy người hỏi (office + level)
  │
WHY   → rò rỉ sai phạm vi = rủi ro #1 → mọi thiết kế phải bảo vệ điều này
  │
HOW   → Scope-before-content, fail-secure default, Clean Architecture
        (xem 2-architecture/clean-architecture.md, 3-technical/contracts.md, 3-technical/data-schema.md)
```

- **HOW không có WHY** → dev không biết khi nào tuyệt đối không được vi phạm quy tắc.
- **WHY không có WHAT** → bảo vệ sai thứ.

Quy trình thực tế là **xoắn ốc**: đi WHAT→WHY→HOW cho một lát cắt mỏng, khi làm HOW phát hiện
câu hỏi nghiệp vụ mới → quay lại bổ sung WHAT/WHY. HOW là nơi *kiểm chứng* WHAT/WHY, không phải kẻ thù.
