"""Leave Type Registry — NGUỒN SỰ THẬT cho taxonomy nghỉ phép (Luật LĐ Việt Nam).

4 rổ theo luật:
  1. Phép năm (công ty trả nguyên lương, TRỪ quỹ phép năm) — dùng cho nghỉ ngơi/việc
     riêng thường ngày.
  2. Việc riêng hưởng lương (công ty trả, KHÔNG trừ phép năm, định mức cố định/sự kiện):
     kết hôn, con kết hôn, tang lễ.
  3. BHXH chi trả (không trừ phép năm, cap riêng): ốm đau, thai sản.
  4. Nghỉ không lương (không ai trả, không cap, phải xin duyệt).

`deduct_pool`: quỹ bị trừ khi DUYỆT — "annual"/"sick"/None. `per_event_cap`: số ngày
tối đa MỖI ĐƠN cho rổ sự kiện (None = không giới hạn theo đơn).

Registry này được expose qua GET /hr/leave-types để FE + agent lấy ĐỘNG (tránh khai
lại lệch ở nhiều nơi).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LeavePolicy:
    code: str
    label_vi: str
    category: int                 # 1..4 (rổ)
    pay_source: str               # "company" | "bhxh" | "none"
    deduct_pool: str | None       # "annual" | "sick" | None
    per_event_cap: int | None     # số ngày tối đa / đơn (rổ sự kiện); None = không giới hạn
    requires_proof: bool          # cần minh chứng (giấy đăng ký kết hôn, giấy tờ...)


LEAVE_POLICIES: dict[str, LeavePolicy] = {
    "annual":         LeavePolicy("annual", "Phép năm", 1, "company", "annual", None, False),
    "marriage":       LeavePolicy("marriage", "Kết hôn", 2, "company", None, 3, True),
    "child_marriage": LeavePolicy("child_marriage", "Con kết hôn", 2, "company", None, 1, True),
    "bereavement":    LeavePolicy("bereavement", "Tang lễ", 2, "company", None, 3, True),
    "sick":           LeavePolicy("sick", "Nghỉ ốm", 3, "bhxh", "sick", None, True),
    "maternity":      LeavePolicy("maternity", "Thai sản", 3, "bhxh", None, None, True),
    "unpaid":         LeavePolicy("unpaid", "Nghỉ không lương", 4, "none", None, None, False),
    # Tương thích ngược: đơn cũ dùng "personal" (việc riêng) — theo luật = dùng phép năm
    # -> hành xử y như annual (trừ quỹ phép năm). Giữ để không vỡ data/đơn pending cũ.
    "personal":       LeavePolicy("personal", "Việc riêng (tính phép năm)", 1, "company", "annual", None, False),
}

# Bộ loại CHÍNH (FE hiển thị) — bỏ "personal" (alias ẩn cho data cũ).
PRIMARY_LEAVE_TYPES: tuple[str, ...] = (
    "annual", "marriage", "child_marriage", "bereavement", "sick", "maternity", "unpaid",
)

ALL_LEAVE_TYPES: tuple[str, ...] = tuple(LEAVE_POLICIES)

_CATEGORY_LABEL = {
    1: "Phép năm (công ty trả)",
    2: "Việc riêng hưởng lương",
    3: "BHXH chi trả",
    4: "Nghỉ không lương",
}


def get_policy(code: str) -> LeavePolicy | None:
    return LEAVE_POLICIES.get((code or "").strip().lower())


def is_valid_type(code: str) -> bool:
    return get_policy(code) is not None


def registry_payload() -> list[dict]:
    """Payload cho GET /hr/leave-types — FE/agent lấy động."""
    return [
        {
            "code": p.code,
            "label_vi": p.label_vi,
            "category": p.category,
            "category_label": _CATEGORY_LABEL.get(p.category, ""),
            "pay_source": p.pay_source,
            "deducts": p.deduct_pool,
            "per_event_cap": p.per_event_cap,
            "requires_proof": p.requires_proof,
        }
        for code in PRIMARY_LEAVE_TYPES
        for p in (LEAVE_POLICIES[code],)
    ]
