-- ─────────────────────────────────────────────────────────────────────────
-- init-db.sql — tạo TẤT CẢ database cho app-postgres in-compose (chạy 1 lần khi
-- postgres khởi tạo volume lần đầu). Thay cho Cloud SQL (provision tay trước đây).
-- Schema + bảng do các one-shot migrate (alembic) lo sau; đây chỉ tạo DB rỗng.
-- ─────────────────────────────────────────────────────────────────────────
CREATE DATABASE user_db;
CREATE DATABASE doc_db;
CREATE DATABASE query_db;
CREATE DATABASE rag_db;
CREATE DATABASE hr_db;
