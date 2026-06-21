"""GATE (consumer runtime): parser NATS query-service PHẢI chấp nhận payload đúng hợp đồng
(event-contracts.yaml) và TỪ CHỐI khi thiếu field định danh. Khóa consumer ⇔ contract: dev
đổi parser 'require' thêm field, hoặc publisher (theo contract) bớt field -> test đỏ.

Bổ trợ nats_contract_lint.py (tĩnh) bằng kiểm CHẠY THẬT trên consumer ACL-trọng-yếu.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.messaging.nats_events import (
    InvalidNatsEventPayload,
    parse_doc_access_event,
    parse_hr_employee_profile_updated_event,
    parse_notify_doc_new_event,
)

_CONTRACT = Path(__file__).resolve().parents[3] / "infra" / "nats" / "event-contracts.yaml"

# query-service tiêu thụ 3 event này; map subject -> parser thật.
_PARSERS = {
    "doc.access": parse_doc_access_event,
    "notify.doc_new": parse_notify_doc_new_event,
    "hr.employee_profile.updated": parse_hr_employee_profile_updated_event,
}


def _load_events() -> dict:
    import yaml
    if not _CONTRACT.exists():
        pytest.skip("event-contracts.yaml không có trong checkout này")
    return (yaml.safe_load(_CONTRACT.read_text(encoding="utf-8")) or {}).get("events") or {}


def _sample_value(field: str):
    """Giá trị mẫu hợp lệ theo tên field (list cho allowed_*, bool cho deleted, str còn lại)."""
    if field.startswith("allowed_"):
        return []
    if field == "deleted":
        return False
    return "x"


def _build_payload(spec: dict, *, include_optional: bool = False) -> dict:
    fields = list(spec.get("meta") or []) + list(spec.get("business_required") or [])
    if include_optional:
        fields += list(spec.get("business_optional") or [])
    payload = {f: _sample_value(f) for f in fields}
    # occurred_at phải là ISO datetime hợp lệ (parser ép kiểu).
    if "occurred_at" in payload:
        payload["occurred_at"] = "2026-06-21T00:00:00Z"
    if "event_version" in payload:
        payload["event_version"] = 1
    return payload


@pytest.mark.parametrize("subject", list(_PARSERS))
def test_parser_accepts_contract_payload(subject):
    """Payload đúng hợp đồng (đủ business_required) -> parser CHẤP NHẬN (không raise)."""
    spec = _load_events().get(subject)
    assert spec, f"event-contracts.yaml thiếu {subject}"
    parser = _PARSERS[subject]
    event = parser(_build_payload(spec))                 # không optional -> vẫn parse
    assert event is not None
    event2 = parser(_build_payload(spec, include_optional=True))  # có optional -> vẫn parse
    assert event2 is not None


@pytest.mark.parametrize("subject", list(_PARSERS))
def test_parser_rejects_missing_identity_field(subject):
    """Bỏ field định danh đầu tiên (doc_id/user_id...) -> parser PHẢI raise (không nuốt im)."""
    spec = _load_events().get(subject)
    parser = _PARSERS[subject]
    payload = _build_payload(spec)
    identity = (spec.get("business_required") or [None])[0]
    payload.pop(identity, None)
    with pytest.raises(InvalidNatsEventPayload):
        parser(payload)
