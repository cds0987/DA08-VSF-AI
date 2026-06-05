from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domain.repositories.document_access_repository import DocumentAccessRepository
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
    ) -> None:
        self._document_access_repo = document_access_repo
        self._notification_service = notification_service
        self._processed_event_ids: set[str] = set()
        self._doc_access_seen_at: dict[str, datetime] = {}
        self._notify_fallback_keys: set[str] = set()

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
        if event.event_id is None and fallback_key in self._notify_fallback_keys:
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
        self._notify_fallback_keys.add(fallback_key)
        return delivered

    def _is_duplicate_event(self, event_id: str | None) -> bool:
        return bool(event_id and event_id in self._processed_event_ids)

    def _remember_event(self, event_id: str | None) -> None:
        if event_id:
            self._processed_event_ids.add(event_id)


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
        return datetime.now(UTC)
    if not isinstance(value, str) or not value.strip():
        raise InvalidNatsEventPayload("occurred_at must be an ISO datetime string")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise InvalidNatsEventPayload("occurred_at must be an ISO datetime string") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
