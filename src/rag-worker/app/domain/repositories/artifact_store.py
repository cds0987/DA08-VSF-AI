from __future__ import annotations

from abc import ABC, abstractmethod


class ArtifactStore(ABC):
    @abstractmethod
    async def write_markdown(self, document_id: str, markdown: str) -> str:
        """Persist canonical markdown artifact and return its stable artifact URI."""

    @abstractmethod
    async def read_markdown(self, artifact_uri: str) -> str:
        """Load canonical markdown artifact from storage."""
