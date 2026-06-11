#!/usr/bin/env python3
"""seed_user.py — bootstrap user_db cho stack e2e (chạy TRONG image user-service).

Prod: user_db (Cloud SQL) được provision + seed TAY một lần -> repo không có chỗ
nào tạo bảng base `user_svc.users` (migration 001 chỉ ALTER bảng giả định đã có)
và không có seed admin. E2e self-contained nên phải tự dựng:

  1. CREATE SCHEMA user_svc
  2. Base.metadata.create_all  -> tạo users/refresh_tokens/audit_logs theo model THẬT
  3. seed 1 admin (đăng nhập được qua user-service như prod): email/password lấy từ
     env SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD, hash bằng CHÍNH BcryptPasswordHasher
     của service -> verify lúc login khớp.

Idempotent: chạy lại không nhân đôi admin (ON CONFLICT email -> bỏ qua).
Dùng engine async của service (asyncpg) -> không thêm dependency mới.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

# Image user-service: WORKDIR=/app, code dưới app/.
from app.infrastructure.db.models import Base, UserModel  # noqa: E402
from app.infrastructure.security.password_hasher import BcryptPasswordHasher  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402


def _db_url() -> str:
    url = os.getenv("USER_SERVICE_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("seed_user: thiếu USER_SERVICE_DATABASE_URL / DATABASE_URL")
    return url


async def _main() -> int:
    email = os.getenv("SEED_ADMIN_EMAIL", "admin@company.com")
    password = os.getenv("SEED_ADMIN_PASSWORD", "***REDACTED-SEED-ADMIN-PW***")
    engine = create_async_engine(_db_url(), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS user_svc")
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as s:
            existing = await s.scalar(select(UserModel).where(UserModel.email == email))
            if existing:
                print(f"seed_user: admin {email} đã tồn tại -> giữ nguyên", flush=True)
                return 0
            s.add(UserModel(
                id=uuid.uuid4(),
                email=email,
                hashed_password=BcryptPasswordHasher().hash(password),
                auth_provider="local",
                role="admin",
                account_type="internal",
                is_active=True,
                department="hr",
            ))
            await s.commit()
        print(f"seed_user: đã seed admin {email}", flush=True)
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(_main()))
    except Exception as exc:  # noqa: BLE001
        print(f"seed_user: FAILED: {exc}", flush=True)
        sys.exit(1)
