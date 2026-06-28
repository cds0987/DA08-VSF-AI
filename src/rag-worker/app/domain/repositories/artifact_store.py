from __future__ import annotations

from abc import ABC, abstractmethod


class ArtifactStore(ABC):
    @abstractmethod
    async def write_markdown(self, document_id: str, markdown: str) -> str:
        """Persist canonical markdown artifact and return its stable artifact URI."""

    @abstractmethod
    async def read_markdown(self, artifact_uri: str) -> str:
        """Load canonical markdown artifact from storage."""

    @abstractmethod
    async def delete_by_document(self, document_id: str) -> None:
        """Delete persisted artifacts for one document, if any."""

    @abstractmethod
    def artifact_uri_for(self, document_id: str) -> str:
        """Deterministic artifact URI cho document_id (KHÔNG I/O).

        write_markdown sinh key ổn định theo document_id -> backfill (re-embed từ MD cache,
        không re-parse) tự suy ra URI để read_markdown mà không cần lưu URI riêng. Khớp
        chính xác key của write_markdown để đọc đúng artifact đã ghi lúc ingest."""
