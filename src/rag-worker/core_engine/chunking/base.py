from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from core_engine.chunking.sections import Section, split_sections


@runtime_checkable
class Chunker(Protocol):
    def split(self, markdown: str) -> list[Section]:
        """Split markdown into semantic sections for ingestion."""


@dataclass(frozen=True)
class SectionChunker:
    parent_max_words: int
    child_max_words: int
    child_overlap_words: int

    def split(self, markdown: str) -> list[Section]:
        return split_sections(
            markdown,
            parent_max_words=self.parent_max_words,
            child_max_words=self.child_max_words,
            child_overlap_words=self.child_overlap_words,
        )
