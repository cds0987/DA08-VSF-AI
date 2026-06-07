from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    last_modified: datetime


class ObjectStoreLister(ABC):
    @abstractmethod
    async def list_objects(self, prefix: str) -> AsyncIterator[StoredObject]:
        """Yield every object under the prefix."""
