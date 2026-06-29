# Tuần 4 — Sprint 3 · Tuần 1/2 · Khởi động Phase 2

> **Sprint:** 3 / 3 · **Phase:** 2 · ⬅️ [Tuần 3](week-3.md) · ➡️ [Tuần 5](week-5.md)

## 🎯 Mục tiêu tuần
Đưa bot vào workflow thực: tích hợp **Microsoft Teams Bot** và bắt đầu **Knowledge Gap Detection** + **dashboard nâng cao**. Tận dụng Azure AD đã setup từ SSO Phase 1.

---

## 📋 Task theo role

| Role | Người | Task tuần này | Phụ thuộc |
|------|-------|---------------|-----------|
| **AI/Agent Engineer** | Phạm Quốc Dũng | **Teams Bot** (`botbuilder-python`) — là MCP client thứ 2 dùng lại tool ở mcp-service; **Knowledge Gap detection** (log câu hỏi có retrieval score < 0.7). | mcp-service (Phase 1), Azure AD |
| **Frontend Dev** | Đặng Hồ Hải | **Admin dashboard nâng cao**: filter/drill-down theo phòng ban & theo tài liệu; danh sách câu hỏi **không trả lời được** / knowledge gaps. | endpoint knowledge gap (AI Eng) |
| **Backend Dev** | Vũ Quang Dũng | Hỗ trợ Teams auth (Azure AD / token); endpoint phục vụ knowledge gap nếu cần (đọc log câu hỏi). | — |
| **RAG Engineer** | Trần Thanh Nguyên | Tune chất lượng theo kết quả eval (T3); hỗ trợ xác định ngưỡng retrieval score cho knowledge gap. | báo cáo eval (T3) |
| **DevOps** | Trần Hữu Gia Huy | Chuẩn bị **backplane** (NATS/Redis pub-sub) cho scale nhiều instance; cấu hình deploy Teams Bot. | — |
| **SA** | Lê Hữu Hưng | Review thiết kế Teams Bot (MCP client) + contract knowledge gap; đảm bảo không phá ranh giới service. | — |

---

## 🔗 Phụ thuộc / điểm chặn
- Teams Bot tái dùng mcp-service + Azure AD (đã có từ SSO) → không phải làm lại auth, ước tính 2–3 ngày (theo roadmap).
- FE dashboard nâng cao cần endpoint knowledge gap (AI Eng) → chốt contract đầu tuần.

## ✅ Definition of Done cuối tuần
- [ ] Hỏi bot **ngay trong Microsoft Teams** (DM hoặc mention) → nhận câu trả lời kèm nguồn tài liệu.
- [ ] **Knowledge Gap**: tự động log câu hỏi retrieval score thấp; Admin xem được danh sách "đang hỏi nhiều về X nhưng chưa có tài liệu".
- [ ] Dashboard nâng cao hiển thị filter/drill-down + danh sách câu hỏi không trả lời được.

## 🔄 Ceremonies
- **Sprint 3 Planning** — đầu Tuần 4: chọn scope Phase 2 cho 2 tuần (T4–T5).
- **Daily standup** — 15'/ngày.
- (Sprint Review của Sprint 3 ở cuối Tuần 5.)
