from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class NatsPublisher:
    """Small adapter kept for future event publishing wiring."""

    async def publish(self, subject: str, payload: dict[str, Any]) -> None:
        return None

    async def aclose(self) -> None:
        return None

