#!/usr/bin/env python3
"""backfill_user_events.py — one-shot go-live: replay `user.created` cho TOÀN BỘ user
hiện có để hr-service tự cấp phát hồ sơ (lấp dữ liệu cũ như admin tạo trước khi có event).

Idempotent: hr consumer dedupe theo event_id/user_id + upsert -> chạy lại vô hại.
Chạy TRONG image user-service (có sẵn model + nats):

    python scripts/backfill_user_events.py

Env: USER_SERVICE_DATABASE_URL / DATABASE_URL, NATS_URL, NATS_JETSTREAM_ENABLED.
"""
from __future__ import annotations

import asyncio
import os
import sys

from app.infrastructure.db.models import UserModel  # noqa: E402
from app.infrastructure.messaging.user_event_publisher import UserEventPublisher  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402


def _db_url() -> str:
    url = os.getenv("USER_SERVICE_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("backfill: thiếu USER_SERVICE_DATABASE_URL / DATABASE_URL")
    return url


def _jetstream_enabled() -> bool:
    return os.getenv("NATS_JETSTREAM_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def _role_value(role: object) -> str:
    value = getattr(role, "value", None)
    return str(value if value is not None else role)


async def _main() -> int:
    engine = create_async_engine(_db_url(), pool_pre_ping=True)
    publisher = UserEventPublisher(
        nats_url=os.getenv("NATS_URL", "nats://nats:4222"),
        jetstream_enabled=_jetstream_enabled(),
    )
    sent = 0
    try:
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as s:
            rows = (await s.scalars(select(UserModel))).all()
        for u in rows:
            await publisher.publish_user_event(
                "user.created",
                {
                    "user_id": str(u.id),
                    "email": u.email,
                    "role": _role_value(u.role),
                    "department": u.department,
                    "account_type": u.account_type,
                    "is_active": u.is_active,
                },
            )
            sent += 1
        print(f"backfill: đã phát user.created cho {sent} user", flush=True)
        return 0
    finally:
        await publisher.close()
        await engine.dispose()


if __name__ == "__main__":
    # Fail-fast: lỗi thoát non-zero ngay, KHÔNG nuốt.
    sys.exit(asyncio.run(_main()))
