from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedArtifact:
    markdown: str
    source_uri: str


class Parser(ABC):
    @abstractmethod
    async def parse(
        self,
        *,
        document_id: str,
        file_type: str,
        source_uri: str,
    ) -> ParsedArtifact:
        """Read a source document through guarded I/O and normalize it to markdown."""

    def close(self) -> None:
        """Release optional parser resources. Default no-op for stateless parsers."""

    def startup_diagnostics(
        self,
        *,
        source_bucket: str | None = None,
    ) -> tuple[list[str], list[str]]:
        """Return (reasons, warnings) discovered during startup. Default = no diagnostics."""
        return [], []
