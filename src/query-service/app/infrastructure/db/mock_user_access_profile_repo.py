from datetime import datetime

from app.domain.repositories.user_access_profile_repository import (
    UserAccessProfile,
    UserAccessProfileRepository,
)


class InMemoryUserAccessProfileRepository(UserAccessProfileRepository):
    """In-memory implementation used in mock/test mode."""

    def __init__(self) -> None:
        self._profiles: dict[str, dict] = {}
        self._updated_at: dict[str, datetime] = {}

    async def upsert_profile(
        self,
        user_id: str,
        account_type: str,
        department: str,
        employment_status: str,
        occurred_at: datetime | None = None,
    ) -> None:
        from datetime import timezone
        now = occurred_at or datetime.now(timezone.utc)
        existing_ts = self._updated_at.get(user_id)
        if existing_ts is not None and existing_ts > now:
            # Ignore stale event (idempotency / out-of-order protection).
            return
        self._profiles[user_id] = {
            "account_type": account_type,
            "department": department,
            "employment_status": employment_status,
        }
        self._updated_at[user_id] = now

    async def get_profile(self, user_id: str) -> UserAccessProfile | None:
        record = self._profiles.get(user_id)
        if record is None:
            return None
        return UserAccessProfile(
            user_id=user_id,
            account_type=str(record["account_type"]),
            department=str(record["department"]),
            employment_status=str(record["employment_status"]),
        )

    async def delete_profile(self, user_id: str) -> None:
        self._profiles.pop(user_id, None)
        self._updated_at.pop(user_id, None)

    async def list_eligible_user_ids(
        self,
        classification: str,
        allowed_departments: list[str],
        allowed_user_ids: list[str],
    ) -> list[str]:
        from app.infrastructure.db.mock_document_access_repo import can_access_document
        return [
            uid for uid, p in self._profiles.items()
            if can_access_document(
                user_id=uid,
                role="user",
                department=str(p.get("department", "")),
                classification=classification,
                account_type=str(p.get("account_type", "internal")),
                allowed_departments=allowed_departments,
                allowed_user_ids=allowed_user_ids,
            )
        ]

    def reset(self) -> None:
        self.__init__()
