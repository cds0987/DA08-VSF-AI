"""Section split — đơn vị NGHĨA (heading-aware), KHÔNG token-chunk mù.

Bám ingestion.md §5: chia theo cấu trúc nghĩa của tác giả (heading); section quá
dài → sub-split (length guard) giữ thứ tự. parent_text = full content (đưa vào LLM
prompt / BM25); children = cửa sổ nhỏ để embed. Khớp `entities.Chunk`.

Không phụ thuộc AI — production thay bằng parser/splitter thật (MarkItDown →
section) qua cùng chữ ký, KHÔNG đổi engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class Section:
    section_title: str
    page_number: int          # placeholder: thứ tự section (parser thật giữ page number)
    parent_text: str          # full content -> LLM prompt
    children: List[str]       # sub-split để embed


def split_sections(
    markdown: str,
    parent_max_words: int,
    child_max_words: int,
    child_overlap_words: int,
) -> List[Section]:
    blocks = _split_by_heading(markdown)
    sections: List[Section] = []
    page = 1
    for title, body in blocks:
        body = body.strip()
        if not body:
            continue
        for parent_text in _cap_words(body, parent_max_words):
            children = _windows(parent_text, child_max_words, child_overlap_words)
            sections.append(
                Section(
                    section_title=title or "(no heading)",
                    page_number=page,
                    parent_text=parent_text,
                    children=children or [parent_text],
                )
            )
        page += 1
    return sections


def _split_by_heading(markdown: str) -> List[Tuple[str, str]]:
    """Tách theo heading markdown (`#`..`######`). Trả [(title, body)]."""
    blocks: List[Tuple[str, str]] = []
    title = ""
    buf: List[str] = []
    for line in markdown.splitlines():
        m = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
        if m:
            if buf or title:
                blocks.append((title, "\n".join(buf)))
            title = m.group(1).strip()
            buf = []
        else:
            buf.append(line)
    if buf or title:
        blocks.append((title, "\n".join(buf)))
    return blocks or [("", markdown)]


def _cap_words(text: str, max_words: int) -> List[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)]


def _windows(text: str, size: int, overlap: int) -> List[str]:
    words = text.split()
    if len(words) <= size:
        return [text]
    step = max(1, size - overlap)
    return [" ".join(words[i : i + size]) for i in range(0, len(words), step)]
