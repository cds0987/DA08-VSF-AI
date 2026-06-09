from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.domain.repositories.document_access_repository import DocumentAccessRepository
from app.domain.repositories.user_access_profile_repository import UserAccessProfileRepository
from app.infrastructure.messaging.notification_service import DocNewEvent, NotificationService


class InvalidNatsEventPayload(ValueError):
    """Raised when an event payload cannot be mapped to the approved contract."""


@dataclass(frozen=True)
class DocAccessEvent:
    doc_id: str
    classification: str
    allowed_departments: list[str]
    allowed_user_ids: list[str]
    deleted: bool
    event_id: str | None
    occurred_at: datetime


@dataclass(frozen=True)
class HrEmployeeProfileUpdatedEvent:
    user_id: str
    account_type: str
    department: str
    employment_status: str
    event_id: str | None
    occurred_at: datetime


@dataclass(frozen=True)
class NotifyDocNewEvent:
    doc_id: str
    document_name: str
    classification: str
    allowed_departments: list[str]
    allowed_user_ids: list[str]
    event_id: str | None
    occurred_at: datetime


class QueryNatsEventHandler:
    def __init__(
        self,
        document_access_repo: DocumentAccessRepository | None = None,
        notification_service: NotificationService | None = None,
        user_access_profile_repo: UserAccessProfileRepository | None = None,
        processed_event_max_size: int = 10000,
        processed_event_ttl_seconds: int = 86400,
    ) -> None:
        self._document_access_repo = document_access_repo
        self._notification_service = notification_service
        self._user_access_profile_repo = user_access_profile_repo
        self._processed_event_ids: OrderedDict[str, datetime] = OrderedDict()
        self._doc_access_seen_at: dict[str, datetime] = {}
        self._notify_fallback_keys: OrderedDict[str, datetime] = OrderedDict()
        self._processed_event_max_size = max(1, processed_event_max_size)
        self._processed_event_ttl = timedelta(seconds=max(1, processed_event_ttl_seconds))

    async def handle_doc_access(self, payload: dict[str, Any]) -> None:
        if self._document_access_repo is None:
            return
        event = parse_doc_access_event(payload)
        if self._is_duplicate_event(event.event_id):
            return
        latest_seen = self._doc_access_seen_at.get(event.doc_id)
        if latest_seen is not None and event.occurred_at < latest_seen:
            self._remember_event(event.event_id)
            return

        if event.deleted:
            await self._document_access_repo.delete_access(event.doc_id)
        else:
            await self._document_access_repo.upsert_access(
                document_id=event.doc_id,
                classification=event.classification,
                allowed_departments=event.allowed_departments,
                allowed_user_ids=event.allowed_user_ids,
                occurred_at=event.occurred_at,
            )
        self._doc_access_seen_at[event.doc_id] = event.occurred_at
        self._remember_event(event.event_id)

    async def handle_notify_doc_new(self, payload: dict[str, Any]):
        if self._notification_service is None:
            return []
        event = parse_notify_doc_new_event(payload)
        if self._is_duplicate_event(event.event_id):
            return []
        fallback_key = f"{event.doc_id}:doc_new"
        if event.event_id is None and self._is_duplicate_fallback_key(fallback_key):
            return []

        delivered = await self._notification_service.publish_doc_new(
            DocNewEvent(
                doc_id=event.doc_id,
                document_name=event.document_name,
                classification=event.classification,
                allowed_departments=event.allowed_departments,
                allowed_user_ids=event.allowed_user_ids,
            )
        )
        self._remember_event(event.event_id)
        self._remember_fallback_key(fallback_key)
        return delivered

    async def handle_hr_employee_profile_updated(self, payload: dict[str, Any]) -> None:
        if self._user_access_profile_repo is None:
            return
        event = parse_hr_employee_profile_updated_event(payload)
        if self._is_duplicate_event(event.event_id):
            return
        await self._user_access_profile_repo.upsert_profile(
            user_id=event.user_id,
            account_type=event.account_type,
            department=event.department,
            employment_status=event.employment_status,
            occurred_at=event.occurred_at,
        )
        self._remember_event(event.event_id)

    def _is_duplicate_event(self, event_id: str | None) -> bool:
        self._prune_store(self._processed_event_ids)
        return bool(event_id and event_id in self._processed_event_ids)

    def _remember_event(self, event_id: str | None) -> None:
        if event_id:
            self._remember_key(self._processed_event_ids, event_id)

    def _is_duplicate_fallback_key(self, key: str) -> bool:
        self._prune_store(self._notify_fallback_keys)
        return key in self._notify_fallback_keys

    def _remember_fallback_key(self, key: str) -> None:
        self._remember_key(self._notify_fallback_keys, key)

    def _remember_key(self, store: OrderedDict[str, datetime], key: str) -> None:
        self._prune_store(store)
        store[key] = datetime.now(timezone.utc)
        store.move_to_end(key)
        while len(store) > self._processed_event_max_size:
            store.popitem(last=False)

    def _prune_store(self, store: OrderedDict[str, datetime]) -> None:
        cutoff = datetime.now(timezone.utc) - self._processed_event_ttl
        expired_keys = [key for key, seen_at in store.items() if seen_at < cutoff]
        for key in expired_keys:
            store.pop(key, None)


def parse_doc_access_event(payload: dict[str, Any]) -> DocAccessEvent:
    return DocAccessEvent(
        doc_id=_required_str(payload, "doc_id"),
        classification=_required_str(payload, "classification"),
        allowed_departments=_string_list(payload.get("allowed_departments"), "allowed_departments"),
        allowed_user_ids=_string_list(payload.get("allowed_user_ids"), "allowed_user_ids"),
        deleted=bool(payload.get("deleted", False)),
        event_id=_optional_str(payload.get("event_id")),
        occurred_at=_event_time(payload.get("occurred_at")),
    )


def parse_hr_employee_profile_updated_event(
    payload: dict[str, Any],
) -> HrEmployeeProfileUpdatedEvent:
    return HrEmployeeProfileUpdatedEvent(
        user_id=_required_str(payload, "user_id"),
        account_type=_required_str(payload, "account_type"),
        department=str(payload.get("department") or ""),
        employment_status=_required_str(payload, "employment_status"),
        event_id=_optional_str(payload.get("event_id")),
        occurred_at=_event_time(payload.get("occurred_at")),
    )


def parse_notify_doc_new_event(payload: dict[str, Any]) -> NotifyDocNewEvent:
    return NotifyDocNewEvent(
        doc_id=_required_str(payload, "doc_id"),
        document_name=_required_str(payload, "document_name"),
        classification=_required_str(payload, "classification"),
        allowed_departments=_string_list(payload.get("allowed_departments"), "allowed_departments"),
        allowed_user_ids=_string_list(payload.get("allowed_user_ids"), "allowed_user_ids"),
        event_id=_optional_str(payload.get("event_id")),
        occurred_at=_event_time(payload.get("occurred_at")),
    )


def _required_str(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise InvalidNatsEventPayload(f"missing required field: {field}")
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise InvalidNatsEventPayload(f"field must be list[str]: {field}")
    return list(value)


def _event_time(value: Any) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        raise InvalidNatsEventPayload("occurred_at must be an ISO datetime string")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise InvalidNatsEventPayload("occurred_at must be an ISO datetime string") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
