# decide/ — V2 design decisions

Thư mục quyết định kiến trúc cho repo v2, distill từ [../handoff/](../handoff/).

## Cấu trúc

```
decide/
├── README.md            # file này — điều hướng
├── concise.md           # V2_HANDOFF master (13 mục): intent, constraints, lessons, risks, open questions
├── NEW_REPO_DECISIONS.md # các quyết định v2 (PROPOSED) — nơi ratify mọi ★
├── diagram/             # sơ đồ Mermaid (cái gì kết nối với cái gì)
│   ├── overview.mermaid         # tổng quan end-to-end, staged 0..8 (chi tiết)
│   ├── overview-compact.mermaid # tổng quan 1 nhìn (rút gọn)
│   ├── ingestion.mermaid        # luồng GHI (logical stages)
│   ├── search.mermaid           # luồng ĐỌC
│   ├── scaling.mermaid          # góc nhìn deployment/scale (worker pool + queue)
│   ├── stateless-integration.mermaid # main orchestrator + helper pools + fallback policy
│   └── execution-modes.mermaid  # D8: MVP→scale, backend interface không đổi (3 mode)
└── technique/           # mô tả kỹ thuật (làm thế nào, đặc tính vận hành)
    ├── overview.md         # ↔ 2 file overview (điểm vào, trỏ tới các doc dưới)
    ├── ingestion.md        # ↔ diagram/ingestion.mermaid
    ├── search.md           # ↔ diagram/search.mermaid
    ├── scaling.md          # ↔ diagram/scaling.mermaid
    │   # --- component technique (chưa có diagram riêng) ---
    ├── parser.md           # stateless parser server (adapter ngoài-process)
    ├── embedding.md        # embedding service / AI gateway
    └── execution-fallback.md # pluggable execution + fallback policy
```

`technique/*.md` nhóm "pipeline" ↔ `diagram/*.mermaid` cùng tên. Nhóm "component"
(parser/embedding/execution-fallback) mô tả từng service tách ra — chưa có diagram riêng.
Lưu ý: mỗi file `.mermaid` chứa **một** diagram → bản chi tiết và bản compact tách 2 file.

## Quy ước

- **Không ★** = ràng buộc/quyết định **grounded trong handoff** (bắt buộc).
- **★** = quyết định v2 **ngoài hoặc còn để-ngỏ** trong handoff → phải ghi `PROPOSED` vào `NEW_REPO_DECISIONS.md` trước khi coi là chốt.
- `diagram/` và `technique/` mô tả **cùng một** pipeline ở hai mức (topology vs cách làm); chúng phải nhất quán với nhau. Cấu trúc **code** (hexagonal) là tầng khác — xem [concise.md](./concise.md) §3, §7.

## Thứ tự đọc

1. [concise.md](./concise.md) — hiểu intent, constraints cứng, lessons, open questions.
2. [diagram/overview-compact.mermaid](./diagram/overview-compact.mermaid) → [diagram/overview.mermaid](./diagram/overview.mermaid) + [technique/overview.md](./technique/overview.md) — nắm toàn cảnh.
3. [diagram/ingestion.mermaid](./diagram/ingestion.mermaid) + [technique/ingestion.md](./technique/ingestion.md) — luồng ghi.
4. [diagram/search.mermaid](./diagram/search.mermaid) + [technique/search.md](./technique/search.md) — luồng đọc.
5. [diagram/scaling.mermaid](./diagram/scaling.mermaid) + [technique/scaling.md](./technique/scaling.md) — scale/deploy.
