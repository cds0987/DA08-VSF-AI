# Kế hoạch theo Sprint — RAG Chatbot

Folder này ghi **kế hoạch cụ thể từng tuần**: ai làm gì, phụ thuộc vào ai, và Definition of Done (DoD) đóng dần theo tuần.

> **Phân vai:**
> - [roadmap.md](../roadmap.md) = *làm gì + DoD theo Phase* (bức tranh lớn).
> - [team-ownership.md](../team-ownership.md) = *ai sở hữu service/file nào* (phân công).
> - **Folder này** = *ai làm gì theo từng tuần* (lịch thực thi).
>
> Mọi task ở đây đều map về owner trong team-ownership.md và DoD trong roadmap.md — không phát sinh việc/owner mới.

---

## Scrum là gì (áp dụng cho dự án này)

Dự án chạy theo **Scrum** — chia thời gian thành các **Sprint** (chu kỳ cố định). Mỗi sprint kết thúc phải ra được **một phần sản phẩm chạy được** (increment). Các nghi thức (ceremonies) mỗi sprint:

| Ceremony | Khi nào | Mục đích |
|----------|---------|----------|
| **Sprint Planning** | Đầu sprint | Chọn việc làm trong sprint từ backlog (roadmap) |
| **Daily Standup** | 15 phút mỗi ngày | Mỗi người: hôm qua làm gì / hôm nay làm gì / vướng gì |
| **Sprint Review** | Cuối sprint | Demo phần sản phẩm vừa làm xong |
| **Retrospective** | Cuối sprint | Rút kinh nghiệm: giữ gì / bỏ gì / cải thiện gì |

---

## Sprint map

Dự án 5 tuần, chia thành **3 sprint**: `[Sprint 1: T1] · [Sprint 2: T2–3] · [Sprint 3: T4–5]`.
**Sprint 1 là sprint 1 tuần** (nền tảng — SA freeze contract, DevOps dựng hạ tầng, team scaffold).

| Sprint | Tuần | Phase (roadmap) | Sprint Goal |
|--------|------|-----------------|-------------|
| **Sprint 1** | 1 | Phase 1 (nền) | SA freeze domain/contracts/schemas; DevOps dựng hạ tầng; team scaffold 5 service |
| **Sprint 2** | 2–3 | Phase 1 + 1.5 | Build core → happy-path E2E → hoàn thiện Phase 1 → deploy AWS → **eval RAGAS (cuối T3)** |
| **Sprint 3** | 4–5 | Phase 2 | Teams Bot + Knowledge Gap + realtime 2 chiều + dashboard nâng cao + **demo cuối (T5)** |

> **Phase 1.5 Evaluation** (eval RAGAS, load test) rơi đúng **cuối Sprint 2 (cuối Tuần 3)** → trùng mốc Sprint 2 Review, là checkpoint quyết định có đi tiếp Phase 2 hay tune thêm.

---

## Kế hoạch từng tuần

| Tuần | File | Sprint | Trọng tâm |
|------|------|--------|-----------|
| 1 | [week-1.md](week-1.md) | Sprint 1 | Freeze nền tảng + scaffold |
| 2 | [week-2.md](week-2.md) | Sprint 2 · T1/2 | Core happy-path E2E (local) |
| 3 | [week-3.md](week-3.md) | Sprint 2 · T2/2 | Hoàn thiện Phase 1 + deploy AWS + Phase 1.5 Eval |
| 4 | [week-4.md](week-4.md) | Sprint 3 · T1/2 | Khởi động Phase 2 (Teams Bot, Knowledge Gap) |
| 5 | [week-5.md](week-5.md) | Sprint 3 · T2/2 | Phase 2 finish + polish + demo cuối |

---

## Team (6 người)

| Role | Người | Service / Folder |
|------|-------|------------------|
| **SA** | Lê Hữu Hưng | `app/domain/` (cả 5 service), contracts, schemas, review |
| **Frontend Dev** | Đặng Hồ Hải | `src/frontend/` (Nuxt 4) |
| **Backend Dev** | Vũ Quang Dũng | `src/user-service/`, `src/document-service/`, `infra/nats/` |
| **RAG Engineer** | Trần Thanh Nguyên | `src/rag-worker/`, `src/mcp-service/` |
| **AI/Agent Engineer** | Phạm Quốc Dũng | `src/query-service/` |
| **DevOps** | Trần Hữu Gia Huy | `infra/`, `docker-compose.yml`, Nginx, AWS, CI/CD |

> Chi tiết file mỗi người sở hữu: xem [team-ownership.md](../team-ownership.md).
