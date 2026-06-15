#!/usr/bin/env python3
"""seed_user.py — bootstrap user_db (chạy TRONG image user-service).

Prod: user_db (Cloud SQL) được provision + seed TAY một lần -> repo không có chỗ
nào tạo bảng base `user_svc.users` (migration 001 chỉ ALTER bảng giả định đã có)
và không có seed admin. E2e self-contained nên phải tự dựng:

  1. CREATE SCHEMA user_svc
  2. Base.metadata.create_all  -> tạo users/refresh_tokens/audit_logs theo model THẬT
  3. seed admin + 2 account TEST (nhân viên + sếp) để nghiệm thu luồng nghỉ phép.

- admin: id uuid4 (ngẫu nhiên), role admin. email/pass từ SEED_ADMIN_*.
- nhân viên / sếp: id TẤT ĐỊNH (uuid5) -> biết trước id sếp để set HR_DEFAULT_APPROVER
  khớp (đơn nghỉ của nhân viên route về sếp; sếp login JWT mang đúng id đó -> duyệt khớp).

Idempotent: đã tồn tại theo email -> bỏ qua. Async engine của service (asyncpg).
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

# Namespace cố định -> uuid5(email) tất định, KHỚP với HR_DEFAULT_APPROVER trong
# hr-service.env (= uuid5 của sếp). ĐỔI namespace = đổi mọi id -> nhớ đổi env.
TEST_NS = uuid.UUID("1b4e28ba-2fa1-11d2-883f-0016d3cca427")


def test_user_id(email: str) -> uuid.UUID:
    return uuid.uuid5(TEST_NS, email)


def _db_url() -> str:
    url = os.getenv("USER_SERVICE_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("seed_user: thiếu USER_SERVICE_DATABASE_URL / DATABASE_URL")
    return url


async def _seed_one(session, hasher, *, uid, email, password, role) -> None:
    existing = await session.scalar(select(UserModel).where(UserModel.email == email))
    if existing:
        print(f"seed_user: {email} đã tồn tại -> giữ nguyên", flush=True)
        return
    session.add(UserModel(
        id=uid,
        email=email,
        hashed_password=hasher.hash(password),
        auth_provider="local",
        role=role,
        account_type="internal",
        is_active=True,
    ))
    await session.commit()
    print(f"seed_user: đã seed {email} (role={role}, id={uid})", flush=True)


async def _main() -> int:
    admin_email = os.getenv("SEED_ADMIN_EMAIL", "admin@company.com")
    admin_password = os.getenv("SEED_ADMIN_PASSWORD", "DemoAdminPassword123!")
    emp_email = os.getenv("SEED_EMPLOYEE_EMAIL", "nhanvien@company.com")
    emp_password = os.getenv("SEED_EMPLOYEE_PASSWORD", "Nhanvien123!")
    boss_email = os.getenv("SEED_MANAGER_EMAIL", "sep@company.com")
    boss_password = os.getenv("SEED_MANAGER_PASSWORD", "Sep123!")

    engine = create_async_engine(_db_url(), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS user_svc")
            await conn.run_sync(Base.metadata.create_all)
        hasher = BcryptPasswordHasher()
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as s:
            # admin: id ngẫu nhiên (giữ hành vi cũ).
            await _seed_one(s, hasher, uid=uuid.uuid4(), email=admin_email,
                            password=admin_password, role="admin")
            # nhân viên + sếp: id TẤT ĐỊNH (uuid5) cho test luồng nghỉ phép.
            await _seed_one(s, hasher, uid=test_user_id(emp_email), email=emp_email,
                            password=emp_password, role="user")
            await _seed_one(s, hasher, uid=test_user_id(boss_email), email=boss_email,
                            password=boss_password, role="user")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(_main()))
    except Exception as exc:  # noqa: BLE001
        print(f"seed_user: FAILED: {exc}", flush=True)
        sys.exit(1)
