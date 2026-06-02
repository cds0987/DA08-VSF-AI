# Architecture Mapping — Tầng 3 (cầu nối WHY → HOW)

> Đây là **mắt xích từng bị đứt**. Nó dịch *quy tắc nghiệp vụ* (domain-model) thành *thành phần
> kiến trúc chịu trách nhiệm thực thi*. Mục tiêu duy nhất: làm mọi lệch pha giữa domain và thiết kế
> **hiện ra dưới dạng một ô trống**, thay vì một tai nạn trong production.
>
> Tài liệu này **chưa nói tới schema/code/framework**. Nó chỉ trả lời: *"Quy tắc X do component nào
> thực thi, và component đó còn thiếu không?"*. Chi tiết kỹ thuật là việc của tầng 4 (làm sau).
>
> ⚠️ Dựng **thuần từ [domain-model.md](../1-domain/domain-model.md)** — không tham chiếu các tài liệu kỹ thuật
> hiện có (đang coi là bản nháp lỗi).

---

## 1. Danh mục component logic (ARCH)

> "Component" ở đây là **đơn vị trách nhiệm nghiệp vụ**, chưa phải service/class. Một component có thể
> nằm trong một hoặc nhiều service khi xuống tầng 4 — đừng vội ánh xạ 1-1.

| ID | Component | Trách nhiệm (một câu) | Aggregate gốc (domain) | Context |
|---|---|---|---|---|
| **ARCH-01** | **Identity Resolver** | Dựng `AccessProfile` của người hỏi: office + cấp bậc + phòng ban + trạng thái | `AccessProfile` | Identity |
| **ARCH-02** | **Scope Evaluator** | Quyết định "profile này có thoả `ScopeOfApplicability` của tài liệu Y không" | `AccessProfile` | Identity |
| **ARCH-03** | **Policy Resolver** | Tìm policy/quyền lợi *áp dụng cho chính người hỏi* theo office + level + thời gian | `Policy` | HR |
| **ARCH-04** | **Sensitive Topic Gate** | Phát hiện chủ đề nhạy cảm/restricted → chặn tự trả lời, kích hoạt escalation | `SensitiveTopic` / `ComplianceGuard` | HR, Finance/Legal |
| **ARCH-05** | **Escalation Router** | Thực hiện Handoff sang người thật khi được kích hoạt | `Conversation` (HandoffRequest) | Conversation |
| **ARCH-06** | **Compliance Guard** | Chốt chặn cuối: không lộ confidential, gắn disclaimer cho phát ngôn ràng buộc | `ComplianceGuard` | Finance/Legal |
| **ARCH-07** | **Grounded Answer Builder** | Chỉ trả lời từ nguồn đã truy hồi; không đủ căn cứ → "không biết" + trích nguồn | (Generic RAG) | Knowledge contexts |
| **ARCH-08** | **Knowledge Eligibility Filter** | Chỉ cấp tài liệu *đủ điều kiện*: là Source of Truth, có owner, còn hiệu lực | `SourceDocument` | Ingestion |
| **ARCH-09** | **Source Adapter (ACL)** | Dịch tài liệu từ Confluence/Slack/Teams sang mô hình nội bộ, gắn nhãn thẩm quyền | `KnowledgeSource` | Ingestion |
| **ARCH-10** | **Identity Adapter (ACL)** | Dịch dữ liệu nhân sự từ HRIS/AD sang `AccessProfile`, chặn mô hình ngoài rò vào lõi | (ranh giới Identity) | Identity |
| **ARCH-11** | **Conversation Orchestrator** | Gắn danh tính vào hội thoại, định tuyến câu hỏi, không rò lịch sử chéo | `Conversation` | Conversation |
| **ARCH-12** | **Audit Recorder** | Ghi truy vết câu trả lời quyền lợi/pháp lý: ai hỏi, trả gì, nguồn nào, **scope nào đã áp** | `AuditEntry` | Finance/Legal |

---

## 2. Ma trận truy vết — Rule → Component → Trạng thái

> Cột **Trạng thái** là phần quan trọng nhất:
> - ✅ **Có** = domain-model đã định nghĩa rõ và đã có component gánh.
> - 🟡 **Mỏng** = có component nhưng phạm vi chưa đủ (thiếu một chiều của domain).
> - ❌ **HỞ** = domain có quy tắc 🔴 nhưng *chưa component nào* thực thi → lỗ hổng phải lấp.
>
> Cột **Ưu tiên**: 🔴 P0 = lõi, phải có ngay (Core Domain / rủi ro cao). 🟡 P1 = quan trọng, ngay sau.

| Rule (tầng 2) | Loại | Component (ARCH) | Phục vụ REQ | Trạng thái | Ưu tiên |
|---|---|---|---|---|---|
| **IA-1** mọi câu hỏi gắn danh tính | 🔴 | ARCH-01, ARCH-11 | REQ-01, REQ-11 | ✅ Có | 🔴 P0 |
| **IA-2** Scope-before-content + default deny | 🔴 | ARCH-02 | REQ-02, REQ-03 | 🟡 **Mỏng** — cơ chế lọc đúng, nhưng scope mới chỉ theo phòng ban/phân loại, **thiếu office + cấp bậc** | 🔴 P0 |
| **IA-3** Terminated → cấm toàn bộ | 🔴 | ARCH-01 | REQ-11 | 🟡 Mỏng — mới dựa trạng thái account, chưa gắn `EmploymentStatus` nghiệp vụ | 🔴 P0 |
| **HR-1** policy đúng người + **đúng hiệu lực** | 🔴 | ARCH-03 | REQ-02, REQ-05 | ❌ **HỞ** — chưa có Policy Resolver; chưa có chiều **thời gian (effective period)** | 🔴 P0 |
| **HR-2** không trộn policy mâu thuẫn, nêu rõ điều kiện | 🔴 | ARCH-03 | REQ-02 | ❌ **HỞ** — chưa có logic chọn policy theo điều kiện office/level | 🔴 P0 |
| **HR-3** không lộ quyền lợi/lương người khác | 🔴 | ARCH-02, ARCH-06 | REQ-03 | ✅ Có (lọc theo chủ thể) | 🔴 P0 |
| **HR-4** chủ đề nhạy cảm → người thật | 🔴 | ARCH-04, ARCH-05 | REQ-07 | ❌ **HỞ** — không có Sensitive Gate, không có Escalation Router | 🔴 P0 |
| **FL-1** không lộ Confidential Document | 🔴 | ARCH-06, ARCH-02 | REQ-03 | 🟡 Mỏng — có khái niệm phân loại mật, chưa có Compliance Guard như chốt chặn riêng | 🔴 P0 |
| **FL-2** không tạo Legal Commitment; có disclaimer | 🔴 | ARCH-06 | REQ-07, REQ-08 | ❌ **HỞ** — chưa có cơ chế disclaimer | 🟡 P1 |
| **FL-3** Restricted Topic → từ chối + người thật | 🔴 | ARCH-04, ARCH-05 | REQ-07 | ❌ **HỞ** — cùng lỗ với HR-4 | 🔴 P0 |
| **FL-4** Grounding bắt buộc + trích nguồn | 🔴 | ARCH-07 | REQ-04 | ✅ Có (fallback + citation) | 🔴 P0 |
| **FL-5** Audit câu trả lời + scope đã áp | 🔴 | ARCH-12 | REQ-08 | 🟡 Mỏng — có log hành động & lưu answer, **chưa ghi scope đã áp** cho mỗi câu trả lời | 🟡 P1 |
| **KI-1** chỉ Source of Truth mới dùng để trả lời | 🔴 | ARCH-08 | REQ-04, REQ-06 | ❌ **HỞ** — chưa phân biệt Source of Truth vs phi chính thức | 🟡 P1 |
| **KI-2** mỗi tài liệu có Document Owner | 🔴 | ARCH-08 | REQ-10 | ❌ **HỞ** — mới có "ai upload", chưa có "ai chịu trách nhiệm" | 🟡 P1 |
| **KI-3** loại tài liệu hết hiệu lực | 🔴 | ARCH-08 | REQ-05 | ❌ **HỞ** — không có chiều thời gian | 🔴 P0 |
| **KI-4** Slack/Teams không tự là Source of Truth | 🔴 | ARCH-09 | REQ-06 | ❌ **HỞ** — chưa ingest các nguồn này, chưa gắn nhãn thẩm quyền | 🟡 P1 |
| **CV-1** hội thoại gắn danh tính, không ẩn danh | 🔴 | ARCH-11 | REQ-01 | ✅ Có | 🔴 P0 |
| **CV-2** yêu cầu escalation → phải Handoff | 🔴 | ARCH-05 | REQ-07 | ❌ **HỞ** — luồng kết thúc ở câu trả lời, không có handoff | 🔴 P0 |
| **CV-3** không rò lịch sử hội thoại chéo | 🔴 | ARCH-11 | REQ-03 | ✅ Có | 🔴 P0 |
| (ranh giới ngoài) Confluence/Slack/Teams → trong | — | ARCH-09 | REQ-06 | ❌ **HỞ** — chưa có ACL nguồn | 🟡 P1 |
| (ranh giới ngoài) HRIS/AD → Identity | — | ARCH-10 | REQ-02 | ❌ **HỞ** — chưa có nguồn cấp office/level | 🔴 P0 |

---

## 3. Tổng hợp lỗ hổng (đọc nhanh)

### 3.1. Lỗ hổng P0 — phải lấp trước khi đi tiếp

| Nhóm lỗ hổng | Rule liên quan | Bản chất |
|---|---|---|
| **Chiều OFFICE + CẤP BẬC trong scope** | IA-2, IA-3, HR-1, HR-2, ARCH-10 | Core Domain. Thiếu cái này = "một câu trả lời cho tất cả" → sai bản chất |
| **Chiều THỜI GIAN (hiệu lực)** | HR-1, KI-3 | Trả lời theo tài liệu hết hạn = quyết định sai, lỗi im lặng |
| **ESCALATION sang người thật** | HR-4, FL-3, CV-2 | Câu hỏi nhạy cảm gặp bot = rủi ro pháp lý/đạo đức cao nhất |
| **POLICY RESOLVER** (chọn policy đúng) | HR-1, HR-2 | Trái tim Core Domain hiện chưa có component nào gánh |

### 3.2. Lỗ hổng P1 — ngay sau P0

- **Source of Truth + Document Owner + ACL nguồn** (KI-1, KI-2, KI-4, ARCH-09): thẩm quyền & trách nhiệm của tri thức.
- **Compliance Guard + disclaimer** (FL-2): phòng vệ phát ngôn ràng buộc pháp lý.
- **Audit ghi scope đã áp** (FL-5): phòng vệ khi tranh chấp.

### 3.3. Phần ĐÃ vững (đừng đập đi)

Bộ khung sau khớp đúng domain, khi lấp lỗ trên thì **tái dùng được**, không xây lại:
`IA-1`, `HR-3`, `FL-4` (grounding/citation), `CV-1`, `CV-3`, và *cơ chế* scope-before-content của `IA-2`
(chỉ cần mở rộng chiều, không đổi cấu trúc).

---

## 4. Lát cắt dọc đầu tiên (để kiểm chứng chuỗi)

> Theo quy tắc xoắn ốc trong [design-flow.md §3.2](../design-flow.md). Chạy hết một lát mỏng xuyên 5 tầng
> trước khi nhân rộng.

**Use case: "Nhân viên Hà Nội cấp nhân viên hỏi số ngày phép còn lại"**

```
REQ-02, REQ-03        cần
   │
   ▼
HR-1, HR-3, IA-2      rule (domain-model)
   │
   ▼
ARCH-01 Identity Resolver  → dựng profile (office=HN, level=nhân viên)
ARCH-02 Scope Evaluator    → lọc policy áp dụng cho profile đó
ARCH-03 Policy Resolver    → chọn đúng chính sách phép HN, còn hiệu lực
ARCH-07 Grounded Answer    → trả lời kèm trích nguồn
ARCH-12 Audit Recorder     → ghi câu trả lời + scope đã áp
   │
   ▼
[tầng 4 — schema/API]      ← thiết kế sau, khi lát cắt này thông
```

Lát cắt này cố tình đi qua **đúng các lỗ hổng P0** (office/level/time + policy resolver). Nếu dựng
được nó end-to-end, phần lớn rủi ro lõi đã được khử. Các use case còn lại nhân rộng theo cùng khuôn.
