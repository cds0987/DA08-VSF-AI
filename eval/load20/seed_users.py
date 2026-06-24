"""Seed N user test qua admin API (POST /api/user/users). Idempotent: 409 (đã có) -> bỏ qua.

Chạy:  python eval/load20/seed_users.py
Cần mạng tới prod (nếu wifi công ty chặn -> đổi mạng, xem memory proxy-domain-blocks-sse).
"""
from __future__ import annotations

import sys

import requests

from common import ADMIN_EMAIL, ADMIN_PW, N_USERS, USER_API, USER_EMAIL, USER_PW


def admin_login(s: requests.Session) -> str:
    r = s.post(f"{USER_API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def main() -> int:
    s = requests.Session()
    try:
        token = admin_login(s)
    except Exception as exc:
        print(f"[FATAL] admin login lỗi: {exc}")
        return 1
    h = {"Authorization": f"Bearer {token}"}
    created, existed, failed = 0, 0, 0
    for i in range(1, N_USERS + 1):
        email = USER_EMAIL(i)
        body = {"email": email, "password": USER_PW, "role": "user", "account_type": "internal"}
        try:
            r = s.post(f"{USER_API}/users", json=body, headers=h, timeout=30)
        except Exception as exc:
            print(f"  [ERR ] {email}: {exc}")
            failed += 1
            continue
        if r.status_code in (200, 201):
            created += 1
            print(f"  [NEW ] {email}")
        elif r.status_code == 409:
            existed += 1
            print(f"  [SKIP] {email} (đã tồn tại)")
        else:
            failed += 1
            print(f"  [FAIL] {email}: HTTP {r.status_code} {r.text[:150]}")
    print(f"\nXong: tạo mới={created} đã có={existed} lỗi={failed} / tổng {N_USERS}")
    # Verify đăng nhập 1 user để chắc seed ăn.
    if created + existed > 0:
        rv = s.post(f"{USER_API}/auth/login",
                    json={"email": USER_EMAIL(1), "password": USER_PW}, timeout=30)
        print(f"Kiểm tra login {USER_EMAIL(1)}: HTTP {rv.status_code} "
              f"({'OK' if rv.status_code == 200 else 'CHECK PW'})")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
