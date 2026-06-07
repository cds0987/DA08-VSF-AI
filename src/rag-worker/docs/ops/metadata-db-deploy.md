# Metadata DB & Deploy — trạng thái hiện tại

> Cập nhật: 2026-06-07. Phạm vi: cấu hình metadata DB (Postgres/Cloud SQL), bước
> migration, và ranh giới với DevOps cho rag-worker. KHÔNG bàn standalone (deploy do
> DevOps quản qua `docker-compose.yml` ở repo root).

## TL;DR

- Metadata DB cấu hình qua **1 biến duy nhất**: `RAG_DATABASE_URL` (rag-worker) /
  `DOC_DATABASE_URL` (document-service).
- **DEFAULT = production (Cloud SQL)** ở cả `docker-compose.yml` (deploy) lẫn
  `docker-compose.localtest.yml` (dev/test). CI **override** về Postgres container local.
- Migration (`alembic upgrade head`) chạy bằng **service one-shot `rag-migrate`** TRƯỚC
  rag-worker — không nhét vào worker startup.
- Code rag-worker **agnostic với vị trí DB**: chỉ phụ thuộc `DATABASE_URL`, đổi
  self-host ↔ Cloud SQL = đổi 1 biến, không sửa code.

## 1. Cấu hình DB — 1 biến, default production

| Ngữ cảnh | `DATABASE_URL` resolve | Cơ chế |
|----------|------------------------|--------|
| Deploy (`docker-compose.yml`) | Cloud SQL | default của `${RAG_DATABASE_URL:-<Cloud SQL>}` |
| Dev chạy tay (localtest, không set biến) | Cloud SQL | default → rag-worker dev + DevOps **cùng 1 DB** |
| CI (`e2e-cloud.yml`) | Postgres container local | workflow set `RAG_DATABASE_URL`/`DOC_DATABASE_URL` = local |

Lý do default = production: cấu hình thật là baseline; môi trường test là ngoại lệ tự
override. Runner GitHub **không tới được** Cloud SQL (authorized networks) + không nên
ghi vào DB prod → CI bắt buộc dùng local container (isolated, `down -v` xóa sạch).

Ràng buộc DB (đọc từ code):
- Driver **BẮT BUỘC** `postgresql+psycopg://` cho rag-worker (KHÔNG asyncpg) —
  `runtime.py` reject nếu sai.
- document-service dùng `postgresql+asyncpg://`.
- Cloud SQL host hiện tại: `34.87.63.152:5432`, DB `rag_db` (rag-worker) / `doc_db`
  (document-service). Mật khẩu có `@` → encode `%40` trong URL.

## 2. Migration tách rời (`rag-migrate`)

`rag-migrate` = service one-shot chạy `alembic upgrade head`, `restart: "no"`,
rag-worker `depends_on: rag-migrate (service_completed_successfully)`. Build-once image
`rag-worker:local` dùng chung cho migrate + worker.

Vì sao KHÔNG nhét migration vào worker startup / Dockerfile CMD:
- **Nhiều worker/replica** tự migrate → chạy đua DDL trên cùng DB → hỏng schema.
- Migration lỗi → **fail-fast** (worker không start) thay vì crash-loop vô hạn.
- Tách "đổi schema" khỏi "chạy app" — restart worker không kéo theo chạy lại alembic.

Schema tạo ra (verify local thành công): `documents`, `ingest_jobs`, `job_logs`,
`alembic_version`.

## 3. Trạng thái tích hợp Cloud SQL

| Hạng mục | Trạng thái |
|----------|-----------|
| Migrate alembic lên Postgres (local) | ✅ verify: exit 0, đủ 4 bảng |
| Cú pháp compose (deploy + localtest + CI override) | ✅ `docker compose config` hợp lệ cả 3 |
| e2e-cloud (ingest→search Qdrant Cloud + GCS + OpenAI thật) | ✅ pass (~2m50s) |
| Kết nối Cloud SQL từ máy dev local | ❌ `Connection refused` — IP dev chưa trong authorized networks |
| Verify migrate/ingest trên Cloud SQL THẬT | ⏳ **chưa** — cần allowlist IP hoặc chạy trên VM |

→ Phần ứng dụng (alembic + repository) đã chứng minh tương đương trên Postgres; delta
chưa kiểm là **mạng/auth tới Cloud SQL** — thuộc hạ tầng DevOps.

## 4. DevOps cần làm khi deploy

1. **CREATE DATABASE** `rag_db` (+ `doc_db/mcp_db/query_db/user_db`) trên Cloud SQL —
   alembic chỉ tạo *bảng*, không tạo database. Thiếu → `rag-migrate` fail-closed.
2. **Mở mạng** VM/host → `34.87.63.152:5432` (authorized networks / private IP /
   Cloud SQL Auth Proxy).
3. (Tùy chọn đổi instance) đặt `RAG_DATABASE_URL` / `DOC_DATABASE_URL` trong `.env`;
   không đặt → dùng default Cloud SQL trong compose.
4. Backup/HA do DevOps quản (Cloud SQL managed).

## 5. Hướng tương lai (chưa làm)

- rag-worker hiện chạy trên **1 server chính**. Phần dự kiến **tách ra sau** là
  **parsing phase** (parse/OCR) khi cần tách khỏi server chính — KHÔNG phải tách DB.
  Hiện giữ parsing in-process, không over-engineer.
- Production: nếu cần, chuyển sang Cloud SQL có HA/PITR = vẫn chỉ đổi `RAG_DATABASE_URL`.
