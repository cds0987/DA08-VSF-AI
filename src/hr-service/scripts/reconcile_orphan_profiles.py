#!/usr/bin/env python3
"""
Reconcile HR profiles mồ côi (orphan) với tài khoản User Service.

Bối cảnh: HR cô lập DB và chỉ dựng hồ sơ từ event NATS (user.created/updated/
deactivated/deleted). Nếu event `user.deleted` bị rớt/không xử lý (vd lúc stream
NATS hỏng) thì hồ sơ HR còn lại dù tài khoản đã bị xóa -> "orphan". Trang Employee
Management hiển thị các dòng này không có STATUS/nút power -> trông lộn xộn.

Script này là CÔNG CỤ VẬN HÀNH (không phải runtime của HR service): nó được phép đọc
cả user_db lẫn hr_db (cùng một Postgres app-postgres) để đối chiếu, rồi xóa hồ sơ HR
nào KHÔNG còn tài khoản tương ứng. Xóa tái dùng PostgresHrRepository.delete_employee_by_user_id
để dọn đúng toàn bộ bảng phụ (leave_requests/balance, attendance, onboarding, benefits,
performance, payroll).

An toàn:
  * MẶC ĐỊNH dry-run — chỉ in ra những gì SẼ xóa, không xóa gì. Phải truyền --apply.
  * Từ chối chạy nếu user_db trả về 0 tài khoản (tránh coi MỌI hồ sơ là orphan khi
    sai URL / DB chưa sẵn sàng).
  * Bỏ qua hồ sơ vừa tạo trong --min-age-minutes (mặc định 60) để không "thu hoạch"
    nhầm hồ sơ đang chờ event user.created tới (eventual consistency).
  * --max-delete-fraction (mặc định 0.5): nếu tỉ lệ orphan vượt ngưỡng thì dừng trừ
    khi có --force (phòng sự cố đối chiếu sai).
  * --keep-user-ids: allowlist (vd seed demo) không bao giờ xóa.

Cách chạy (trong môi trường có deps của hr-service):
  USER_DATABASE_URL=postgresql+psycopg://postgres:<pw>@app-postgres:5432/user_db \
  HR_DATABASE_URL=postgresql+psycopg://postgres:<pw>@app-postgres:5432/hr_db \
  python scripts/reconcile_orphan_profiles.py            # dry-run
  ... --apply                                            # thực thi xóa
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import sys
from dataclasses import dataclass

# Heavy deps (sqlalchemy, package `app`) được import LAZY trong từng hàm để compute_orphans()
# unit-test được mà không cần DB/env. _ensure_app_on_path() thêm src/hr-service vào sys.path
# khi chạy standalone từ thư mục scripts/.
def _ensure_app_on_path() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)


@dataclass(frozen=True)
class Profile:
    user_id: str
    company_email: str
    created_at: datetime.datetime | None


def compute_orphans(
    profiles: list[Profile],
    valid_user_ids: set[str],
    *,
    now: datetime.datetime,
    min_age_minutes: int,
    keep_user_ids: set[str],
) -> list[Profile]:
    """Hồ sơ là orphan khi user_id KHÔNG có trong tập tài khoản hợp lệ. Bỏ qua hồ sơ
    nằm trong allowlist và hồ sơ mới tạo (< min_age_minutes) để tránh xóa nhầm do trễ event.
    Hàm thuần (không I/O) để test dễ."""
    cutoff = now - datetime.timedelta(minutes=min_age_minutes)
    orphans: list[Profile] = []
    for p in profiles:
        if p.user_id in valid_user_ids:
            continue
        if p.user_id in keep_user_ids:
            continue
        if p.created_at is not None and p.created_at > cutoff:
            continue  # quá mới — có thể event user.created chưa tới, đừng đụng
        orphans.append(p)
    return orphans


def _fetch_valid_user_ids(user_db_url: str) -> set[str]:
    import sqlalchemy as sa

    engine = sa.create_engine(user_db_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sa.text("SELECT id FROM user_svc.users")).fetchall()
        return {str(r[0]) for r in rows}
    finally:
        engine.dispose()


def _fetch_hr_profiles(hr_db_url: str) -> list[Profile]:
    import sqlalchemy as sa

    engine = sa.create_engine(hr_db_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT user_id, company_email, created_at "
                    "FROM hr_svc.employees ORDER BY created_at"
                )
            ).fetchall()
        return [Profile(user_id=str(r[0]), company_email=str(r[1]), created_at=r[2]) for r in rows]
    finally:
        engine.dispose()


async def _delete_orphans(hr_db_url: str, orphans: list[Profile]) -> int:
    from app.infrastructure.db.postgres_hr_repository import PostgresHrRepository

    repo = PostgresHrRepository(hr_db_url)
    deleted = 0
    try:
        for p in orphans:
            ok = await repo.delete_employee_by_user_id(p.user_id)
            mark = "deleted" if ok else "no-op"
            print(f"    [{mark}] {p.user_id}  {p.company_email}")
            if ok:
                deleted += 1
    finally:
        aclose = getattr(repo, "aclose", None)
        if aclose is not None:
            await aclose()
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile orphan HR profiles vs User Service accounts")
    parser.add_argument("--apply", action="store_true", help="Thực sự xóa (mặc định dry-run)")
    parser.add_argument("--min-age-minutes", type=int, default=60,
                        help="Bỏ qua hồ sơ mới tạo trong N phút (mặc định 60)")
    parser.add_argument("--max-delete-fraction", type=float, default=0.5,
                        help="Dừng nếu orphan vượt tỉ lệ này, trừ khi --force (mặc định 0.5)")
    parser.add_argument("--force", action="store_true", help="Bỏ qua guard tỉ lệ")
    parser.add_argument("--keep-user-ids", default="",
                        help="Danh sách user_id (phẩy) không bao giờ xóa (allowlist)")
    args = parser.parse_args()

    user_db_url = os.getenv("USER_DATABASE_URL", "").strip()
    if not user_db_url:
        print("ERROR: thiếu env USER_DATABASE_URL (URL tới user_db).", file=sys.stderr)
        return 2

    _ensure_app_on_path()
    from app.core.config import get_settings

    hr_db_url = get_settings().database_url

    keep_ids = {x.strip() for x in args.keep_user_ids.split(",") if x.strip()}

    valid_ids = _fetch_valid_user_ids(user_db_url)
    if not valid_ids:
        print("ERROR: user_db trả về 0 tài khoản — từ chối chạy (tránh xóa toàn bộ hồ sơ).",
              file=sys.stderr)
        return 2

    profiles = _fetch_hr_profiles(hr_db_url)
    now = datetime.datetime.now(datetime.timezone.utc)
    orphans = compute_orphans(
        profiles, valid_ids,
        now=now, min_age_minutes=args.min_age_minutes, keep_user_ids=keep_ids,
    )

    print(f"User accounts hợp lệ: {len(valid_ids)}")
    print(f"HR profiles tổng:     {len(profiles)}")
    print(f"Orphan phát hiện:     {len(orphans)}")
    for p in orphans:
        print(f"    - {p.user_id}  {p.company_email}  (created={p.created_at})")

    if not orphans:
        print("Không có orphan. Xong.")
        return 0

    fraction = len(orphans) / len(profiles) if profiles else 0
    if fraction > args.max_delete_fraction and not args.force:
        print(f"ABORT: orphan {fraction:.0%} > ngưỡng {args.max_delete_fraction:.0%}. "
              f"Kiểm tra lại đối chiếu; dùng --force nếu chắc chắn.", file=sys.stderr)
        return 3

    if not args.apply:
        print("\n[dry-run] Không xóa gì. Chạy lại với --apply để thực thi.")
        return 0

    print("\n[apply] Đang xóa orphan...")
    deleted = asyncio.run(_delete_orphans(hr_db_url, orphans))
    print(f"Hoàn tất: đã xóa {deleted}/{len(orphans)} hồ sơ orphan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
