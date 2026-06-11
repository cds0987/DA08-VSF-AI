-- ─────────────────────────────────────────────────────────────────────────
-- init-db.sql — tạo TẤT CẢ database cho stack e2e (chạy 1 lần khi postgres init).
-- Prod dùng Cloud SQL với các DB này đã được provision tay; e2e mô phỏng bằng
-- 1 postgres container -> phải tự tạo. Schema + bảng + seed do các one-shot
-- (seed-user, seed-doc, rag-migrate, hr-migrate) và query-service tự lo sau đó.
-- ─────────────────────────────────────────────────────────────────────────
CREATE DATABASE user_db;
CREATE DATABASE doc_db;
CREATE DATABASE query_db;
CREATE DATABASE rag_db;
CREATE DATABASE hr_db;
