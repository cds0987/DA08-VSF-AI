import json
from typing import Iterable

from app.application.auth import CurrentUser
from app.application.exceptions import PermissionDeniedError, ValidationError
from app.application.use_cases.documents.supported_formats import (
    resolve_allowed_extensions,
)
from app.core.config import get_settings


ALLOWED_CLASSIFICATIONS = {"public", "internal", "secret", "top_secret"}
# Loại file được chấp nhận = (rag-worker parse được, từ supported_formats.json)
# ∩ (allow_list chính sách qua DOC_ALLOWED_EXTENSIONS). rag-worker là nguồn chân lý;
# manifest sinh từ scripts/gen_supported_formats.py, parity check ở
# rag-worker/tests/infrastructure/test_parser_parity.py.
ALLOWED_EXTENSIONS = resolve_allowed_extensions(get_settings().allowed_extensions)
MAX_FILE_BYTES = 50 * 1024 * 1024


def require_admin(actor: CurrentUser) -> None:
    if actor.role != "admin":
        raise PermissionDeniedError()


def normalize_acl_values(values: Iterable[str] | str | None) -> list[str]:
    if values is None:
        return []
    raw_values = [values] if isinstance(values, str) else list(values)
    normalized: list[str] = []
    for value in raw_values:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                normalized.extend(str(item).strip() for item in parsed if str(item).strip())
                continue
        normalized.extend(part.strip() for part in text.split(",") if part.strip())
    return list(dict.fromkeys(normalized))


def validate_classification_and_acl(
    classification: str,
    allowed_departments: list[str],
    allowed_user_ids: list[str],
) -> None:
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise ValidationError("Invalid classification")
    if classification == "secret" and not allowed_departments:
        raise ValidationError("allowed_departments is required for secret documents")
    if classification == "top_secret" and not allowed_user_ids:
        raise ValidationError("allowed_user_ids is required for top_secret documents")


def can_access_document(
    user: CurrentUser,
    classification: str,
    allowed_departments: list[str],
    allowed_user_ids: list[str],
) -> bool:
    if user.role == "admin":
        return True
    if classification == "public":
        return True
    if classification == "internal":
        return user.account_type == "internal"
    if classification == "secret":
        if user.account_type != "internal":
            return False
        department = user.department.strip()
        if not department:
            return False
        normalized_departments = {item.strip() for item in allowed_departments if item.strip()}
        return department in normalized_departments
    if classification == "top_secret":
        return user.id in allowed_user_ids
    return False
