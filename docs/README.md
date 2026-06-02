# Docs — Mục lục

Tài liệu được tổ chức theo **chuỗi thiết kế 5 tầng**: mỗi quyết định ở tầng dưới truy ngược được
về một lý do ở tầng trên. Đọc [design-flow.md](design-flow.md) trước để hiểu trật tự & cách truy vết.

```
design-flow.md ............. 🗺️  Bản đồ — đọc đầu tiên
│
├── 0-requirements/ ......... Tầng 0 — Nghiệp vụ cần gì?
│     └── problem-and-market.md
│
├── 1-domain/ ............... Tầng 1–2 — WHAT + WHY (domain, quy tắc, lý do)
│     └── domain-model.md
│
├── 2-architecture/ ......... Tầng 3 — Cầu nối WHY → HOW
│     ├── architecture-mapping.md ...... ⭐ ma trận truy vết rule → component
│     ├── solution-architecture.md ..... kiến trúc giải pháp tổng thể
│     └── clean-architecture.md ........ Clean Architecture 4 layer
│
├── 3-technical/ ........... Tầng 4 — Chi tiết kỹ thuật (HOW cụ thể)
│     ├── contracts.md ........ domain interfaces
│     ├── data-schema.md ...... PostgreSQL + Qdrant schema
│     └── api-spec.md ......... HTTP endpoints
│
├── delivery/ .............. Cắt ngang — lộ trình & phân công
│     ├── roadmap.md
│     └── team-ownership.md
│
└── operations/ ........... Cắt ngang — cài đặt & vận hành
      ├── setup.md
      └── env-setup.md
```

## Bảng tra nhanh

| Bạn muốn biết… | Đọc |
|---|---|
| Trật tự đọc & cách truy vết | [design-flow.md](design-flow.md) |
| Bài toán nghiệp vụ, thị trường | [0-requirements/problem-and-market.md](0-requirements/problem-and-market.md) |
| Domain, ngôn ngữ chung, quy tắc + lý do | [1-domain/domain-model.md](1-domain/domain-model.md) |
| Quy tắc nào do component nào thực thi (lỗ hổng) | [2-architecture/architecture-mapping.md](2-architecture/architecture-mapping.md) |
| Kiến trúc giải pháp tổng thể | [2-architecture/solution-architecture.md](2-architecture/solution-architecture.md) |
| Quy ước Clean Architecture | [2-architecture/clean-architecture.md](2-architecture/clean-architecture.md) |
| Interface / schema / API cụ thể | [3-technical/](3-technical/) |
| Lộ trình phase, ai làm gì | [delivery/](delivery/) |
| Cài đặt, biến môi trường | [operations/](operations/) |

> ⚠️ **Trạng thái:** các tài liệu trong `2-architecture/` (phần kỹ thuật) và `3-technical/` đang được
> coi là **bản nháp lỗi** — sẽ đối soát lại với [2-architecture/architecture-mapping.md](2-architecture/architecture-mapping.md)
> (xem các ô `❌ HỞ`) trước khi chốt.
