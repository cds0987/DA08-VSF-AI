from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class Publisher(Protocol):
    async def publish(self, subject: str, payload: dict[str, Any]) -> None:
        ...


@dataclass
class EmployeeProfileService:
    publisher: Publisher

    async def publish_profile_updated(self, payload: dict[str, Any]) -> None:
        await self.publisher.publish("hr.employee_profile.updated", payload)

