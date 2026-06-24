from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UserAccessProfile:
    user_id: str
    account_type: str
    department: str
    employment_status: str


class UserAccessProfileRepository(ABC):
    @abstractmethod
    async def upsert_profile(
        self,
        user_id: str,
        account_type: str,
        department: str,
        employment_status: str,
        occurred_at: datetime | None = None,
    ) -> None:
        """Upsert user access profile from hr.employee_profile.updated events."""

    @abstractmethod
    async def get_profile(self, user_id: str) -> UserAccessProfile | None:
        """Return the locally cached user access profile, or None if not yet projected."""

    @abstractmethod
    async def delete_profile(self, user_id: str) -> None:
        """Delete user access profile (called when user is deleted)."""
