"""Khóa hành vi Leave Type Registry (4 rổ luật LĐ VN)."""
from app.domain.leave_policy import (
    PRIMARY_LEAVE_TYPES,
    get_policy,
    is_valid_type,
    registry_payload,
)


def test_primary_types_and_validity():
    assert set(PRIMARY_LEAVE_TYPES) == {
        "annual", "marriage", "child_marriage", "bereavement", "sick", "maternity", "unpaid",
    }
    assert is_valid_type("annual")
    assert is_valid_type("ANNUAL")  # case-insensitive
    assert not is_valid_type("xyz")


def test_deduction_pools():
    # Rổ 1 -> trừ phép năm; rổ 3 ốm -> trừ sick; rổ 2/4 -> không trừ.
    assert get_policy("annual").deduct_pool == "annual"
    assert get_policy("sick").deduct_pool == "sick"
    assert get_policy("marriage").deduct_pool is None
    assert get_policy("bereavement").deduct_pool is None
    assert get_policy("unpaid").deduct_pool is None
    assert get_policy("maternity").deduct_pool is None


def test_per_event_caps():
    assert get_policy("marriage").per_event_cap == 3
    assert get_policy("child_marriage").per_event_cap == 1
    assert get_policy("bereavement").per_event_cap == 3
    assert get_policy("annual").per_event_cap is None  # phép năm không cap/đơn


def test_personal_alias_behaves_as_annual():
    # Đơn cũ dùng 'personal' (việc riêng) -> theo luật tính vào phép năm.
    assert get_policy("personal").deduct_pool == "annual"
    assert get_policy("personal").category == 1


def test_registry_payload_shape():
    payload = registry_payload()
    codes = [p["code"] for p in payload]
    assert "annual" in codes and "personal" not in codes  # alias ẩn khỏi FE
    sample = next(p for p in payload if p["code"] == "marriage")
    assert sample["per_event_cap"] == 3
    assert sample["category"] == 2
    assert sample["pay_source"] == "company"
