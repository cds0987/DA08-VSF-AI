import datetime
import importlib.util
import os
import sys

# Import module script trực tiếp theo path (scripts/ không phải package). compute_orphans
# là hàm thuần, các import nặng (sqlalchemy/app) đã lazy nên load module không cần DB/env.
_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "reconcile_orphan_profiles.py",
)
_spec = importlib.util.spec_from_file_location("reconcile_orphan_profiles", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
# Đăng ký vào sys.modules trước khi exec để @dataclass (with future annotations) resolve được.
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
compute_orphans = _mod.compute_orphans
Profile = _mod.Profile

NOW = datetime.datetime(2026, 6, 18, 12, 0, tzinfo=datetime.timezone.utc)


def _p(user_id: str, *, minutes_old: int = 600) -> Profile:
    return Profile(
        user_id=user_id,
        company_email=f"{user_id}@example.com",
        created_at=NOW - datetime.timedelta(minutes=minutes_old),
    )


def _orphans(profiles, valid, *, keep=None, min_age=60):
    return compute_orphans(
        profiles, set(valid),
        now=NOW, min_age_minutes=min_age, keep_user_ids=set(keep or []),
    )


def test_profile_with_account_is_not_orphan() -> None:
    assert _orphans([_p("u1")], ["u1"]) == []


def test_profile_without_account_is_orphan() -> None:
    out = _orphans([_p("u1")], ["u2"])
    assert [p.user_id for p in out] == ["u1"]


def test_keep_list_protects_profile() -> None:
    assert _orphans([_p("seed")], ["other"], keep=["seed"]) == []


def test_fresh_profile_skipped_within_min_age() -> None:
    # Hồ sơ mới tạo 5 phút trước, min_age 60 -> bỏ qua (event user.created có thể chưa tới).
    assert _orphans([_p("u1", minutes_old=5)], ["u2"], min_age=60) == []


def test_fresh_profile_collected_once_old_enough() -> None:
    out = _orphans([_p("u1", minutes_old=120)], ["u2"], min_age=60)
    assert [p.user_id for p in out] == ["u1"]


def test_created_at_none_is_collected() -> None:
    p = Profile(user_id="u1", company_email="x", created_at=None)
    out = _orphans([p], ["u2"])
    assert [x.user_id for x in out] == ["u1"]
