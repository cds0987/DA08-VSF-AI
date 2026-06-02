# Design Flow — Chuỗi thiết kế có truy vết

> Tài liệu **bản đồ**. Nó định nghĩa *thứ tự* các tầng thiết kế và *cách một quyết định kỹ thuật
> truy ngược về một lý do nghiệp vụ*. Đọc file này trước khi đọc bất kỳ tài liệu thiết kế nào khác.
>
> ⚠️ **Lưu ý trạng thái:** Các tài liệu kỹ thuật hiện có trong `docs/`
> ([architecture.md](architecture.md), [contracts.md](contracts.md), [data-schema.md](data-schema.md),
> [api-spec.md](api-spec.md), và phần kỹ thuật của [SA_RAG_Chatbot_Final.md](SA_RAG_Chatbot_Final.md))
> đang được coi là **bản nháp lỗi** — sẽ đối soát lại với chuỗi này sau. Chuỗi dưới đây được dựng
> **từ nghiệp vụ xuống**, không bị ràng buộc bởi thiết kế kỹ thuật hiện tại.

---

## 1. Vì sao cần chuỗi này

Bài đối chiếu trước đã cho thấy: các luồng design lệch khỏi domain (thiếu office/level scoping,
thiếu temporal validity, thiếu escalation) mà **không ai phát hiện** cho đến khi soi tay từng bước.

Nguyên nhân gốc: **không có sợi dây truy vết** nối *quyết định kỹ thuật* ↔ *quy tắc nghiệp vụ* ↔
*yêu cầu*. Chuỗi này là sợi dây đó. Khi có nó, mọi lệch pha lộ ra ngay dưới dạng một ô trống trong
ma trận, thay vì một tai nạn trong production.

---

## 2. Năm tầng

| Tầng | Trả lời câu hỏi | Artifact | Tiền tố ID | File |
|---|---|---|---|---|
| **0. Requirement** | Nghiệp vụ cần gì? Ràng buộc gì? | Sổ đăng ký yêu cầu | `REQ-xx` | file này, §4 |
| **1. Phân tích** | Domain gì? Context nào? Rủi ro nào? | DDD strategic | `CTX-x`, `RISK-x` | [domain-model.md](domain-model.md) §1, 3, 6 |
| **2. Domain Model** | "Đúng" là gì? Quy tắc & lý do? | Ngôn ngữ chung, quy tắc, building blocks | `IA-x`, `HR-x`, `FL-x`, `KI-x`, `CV-x`, `IT-x` | [domain-model.md](domain-model.md) §2, 4, 5 |
| **3. Architecture Mapping** ⭐ | Quy tắc nào do component nào thực thi? | Ma trận truy vết | `ARCH-xx` | [architecture-mapping.md](architecture-mapping.md) |
| **4. Chi tiết kỹ thuật** | Schema / API / interface cụ thể? | DDL, endpoints, contracts | `TECH-xx` | *(sẽ làm lại sau khi 0–3 ổn định)* |

> Tầng 2 đã có ID sẵn trong domain-model (`IA-1`, `HR-1`...). Chuỗi này **tái dùng**, không phát minh ID mới.

---

## 3. Hai quy tắc vận hành

### 3.1. Quy tắc truy vết (bắt buộc)

> **Mỗi dòng ở tầng dưới phải trích được ID của tầng trên.**

```
REQ-02  ──cần──▶  HR-1   ──thực thi bởi──▶  ARCH-03 (Policy Resolver)
"đúng phạm vi      (rule,    Policy Resolver        ──hiện thực──▶  TECH-xx
 office+level"      domain)                          (schema + API)
```

Hệ quả kiểm soát chất lượng — chạy như checklist:
- Một **REQ** không dẫn tới rule nào → yêu cầu bị bỏ quên.
- Một **rule 🔴** không component (ARCH) nào thực thi → **lỗ hổng nghiệp vụ**.
- Một **component** không trỏ về rule nào → thừa, có thể là over-engineering.

### 3.2. Quy tắc xoắn ốc (không waterfall)

Không viết xong 100% tầng trên rồi mới xuống tầng dưới. Đi **một lát cắt dọc mỏng** xuyên cả 5 tầng,
học được gì thì **quay lên sửa tầng trên**. Tầng dưới là nơi *kiểm chứng* tầng trên, không phải kẻ thù.

> Lát cắt đầu tiên đề xuất: **"Nhân viên hỏi số ngày phép còn lại"** — đi xuyên REQ-02/03 → HR-1/HR-3
> → ARCH (Policy Resolver + Scope Evaluator) → schema. Chạy hết một lát rồi mới nhân rộng.

---

## 4. Sổ đăng ký Requirement (Tầng 0)

> Trích từ bài toán nghiệp vụ gốc (không từ tài liệu kỹ thuật). Mỗi REQ có ID để các tầng dưới trỏ về.
> Cột **Context** cho biết yêu cầu thuộc bounded context nào (xem [domain-model §3](domain-model.md)).

| ID | Yêu cầu nghiệp vụ | Context | Rule liên quan (tầng 2) |
|---|---|---|---|
| **REQ-01** | Nhân viên tra cứu chính sách/tài liệu nội bộ bằng ngôn ngữ tự nhiên | Conversation, các Knowledge context | CV-1 |
| **REQ-02** | Câu trả lời phải **đúng phạm vi áp dụng cho chính người hỏi** (theo office + cấp bậc) | Identity, HR | IA-2, HR-1, HR-2 |
| **REQ-03** | Không rò rỉ thông tin ngoài phạm vi của người hỏi (rủi ro #1) | Identity | IA-2, IA-3, HR-3 |
| **REQ-04** | Mọi câu trả lời về policy/quyền lợi phải **trích dẫn nguồn**; không nguồn → "không biết" | mọi Knowledge context | FL-4, KI-1 |
| **REQ-05** | Chính sách thay đổi theo thời gian — chỉ dùng **bản còn hiệu lực** với người đó | HR, Ingestion | HR-1, KI-3 |
| **REQ-06** | Tri thức đến từ **Confluence / Slack / Teams** — nhiều nguồn, thẩm quyền khác nhau | Ingestion | KI-1, KI-2, KI-4 |
| **REQ-07** | Câu hỏi **nhạy cảm** (sa thải, kỷ luật, tranh chấp, pháp lý) phải **chuyển người thật** | HR, Finance/Legal, Conversation | HR-4, FL-3, CV-2 |
| **REQ-08** | **Truy vết** được mọi câu trả lời quyền lợi/pháp lý (ai hỏi, trả gì, nguồn nào, scope nào) | Finance/Legal | FL-5 |
| **REQ-09** | Phục vụ nhiều phòng ban: HR / IT / Finance / Legal / Operations — mỗi nơi ngôn ngữ riêng | tất cả | (ranh giới context) |
| **REQ-10** | Quản trị vòng đời tài liệu: đưa vào kho, ai **chịu trách nhiệm tính đúng** | Ingestion | KI-2 |
| **REQ-11** | Nhân viên đã nghỉ việc / hết quyền không được truy cập | Identity | IA-1, IA-3 |

**Ràng buộc nền (constraints):**

| ID | Ràng buộc |
|---|---|
| **CON-1** | Quy mô ~4000 nhân viên; 2 văn phòng: Hà Nội, HCM |
| **CON-2** | Chính sách có thể khác theo **văn phòng** và **cấp bậc** |
| **CON-3** | Hệ thống tri thức hiện hữu: Confluence, Slack, Microsoft Teams |
| **CON-4** | Tuân thủ bảo vệ dữ liệu cá nhân nội bộ |

---

## 5. Thứ tự đọc tài liệu

```
design-flow.md (file này)  ← bản đồ, đọc đầu tiên
        │
        ▼
domain-model.md            ← WHAT + WHY (tầng 1–2)
        │
        ▼
architecture-mapping.md    ← cầu nối WHY → HOW (tầng 3)
        │
        ▼
[tài liệu kỹ thuật]         ← HOW chi tiết (tầng 4) — làm lại sau
```

## 6. Mỗi PR phải trỏ về đâu

Khi mở PR, mô tả phải nêu: *PR này hiện thực `ARCH-xx`, thực thi rule `HR-1`, phục vụ `REQ-02`.*
Nếu không trỏ ngược được → hoặc PR thừa, hoặc thiếu một tầng chưa được định nghĩa. Dừng lại, bổ sung tầng đó trước.
