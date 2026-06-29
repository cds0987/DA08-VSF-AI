# Tuần 5 — Sprint 3 · Tuần 2/2 · Phase 2 finish + Demo

> **Sprint:** 3 / 3 · **Phase:** 2 · ⬅️ [Tuần 4](week-4.md) · 🏁 [README](README.md)

## 🎯 Mục tiêu tuần
Hoàn thiện **realtime 2 chiều nâng cao**, đóng nốt dashboard 4 metrics, polish toàn hệ và **demo cuối**.

---

## 📋 Task theo role

| Role | Người | Task tuần này | Phụ thuộc |
|------|-------|---------------|-----------|
| **AI/Agent Engineer** | Phạm Quốc Dũng | Mở rộng loại notify (admin đăng chính sách mới, nhắc cá nhân); **typing indicator**; route sự kiện qua backplane khi scale nhiều instance. | backplane (DevOps, T4) |
| **Frontend Dev** | Đặng Hồ Hải | Hoàn thiện dashboard đủ **4 metrics** (volume, feedback rate, top questions, knowledge gaps); UI typing indicator; polish UX + responsive. | endpoint metrics đầy đủ |
| **DevOps** | Trần Hữu Gia Huy | Hoàn tất **backplane** (NATS/Redis pub-sub) cho multi-instance; smoke test cuối; chuẩn bị môi trường demo ổn định. | — |
| **Backend Dev** | Vũ Quang Dũng | Fix bug tồn từ eval; hỗ trợ mở rộng loại notify (publish event mới nếu cần). | — |
| **RAG Engineer** | Trần Thanh Nguyên | Tune cuối theo eval; fix bug retrieval/ingestion; chốt chunk config. | — |
| **SA** | Lê Hữu Hưng | Review cuối; chốt tài liệu kiến trúc khớp với hệ đã build; chuẩn bị nội dung demo. | — |

---

## 🔗 Phụ thuộc / điểm chặn
- Realtime nâng cao (typing, multi-instance) cần backplane (DevOps) xong từ T4.
- Tuần polish → ưu tiên **freeze tính năng giữa tuần**, dành cuối tuần cho demo + retro tổng.

## ✅ Definition of Done cuối tuần
- [ ] **Toàn bộ DoD Phase 2** đóng: dashboard đủ 4 metrics; knowledge gaps visible; hỏi được trong Microsoft Teams; notify hoạt động khi scale nhiều instance (qua backplane) + có typing indicator.
- [ ] Smoke test cuối pass; hệ chạy ổn định trên GCP.
- [ ] Demo cuối hoàn chỉnh.

## 🔄 Ceremonies
- **Daily standup** — 15'/ngày.
- **Sprint 3 Review** — cuối Tuần 5: **demo cuối** toàn sản phẩm (Phase 1 + Phase 2).
- **Retrospective tổng** — rút kinh nghiệm cả 3 sprint, định hướng tầm nhìn dài hạn (Phase 3+ trong [roadmap.md](../roadmap.md)).
