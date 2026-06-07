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
    section_index: int        # placeholder: thứ tự section, chưa phải page PDF thực
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
    section_index = 1
    for title, body in blocks:
        body = body.strip()
        if not body:
            continue
        for parent_text in _cap_words(body, parent_max_words):
            children = _windows(parent_text, child_max_words, child_overlap_words)
            sections.append(
                Section(
                    section_title=title or "(no heading)",
                    section_index=section_index,
                    parent_text=parent_text,
                    children=children or [parent_text],
                )
            )
        section_index += 1
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
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]
    if not sentences:
        return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)]

    chunks: List[str] = []
    current: List[str] = []
    current_count = 0
    for sentence in sentences:
        sentence_words = sentence.split()
        sentence_count = len(sentence_words)
        if sentence_count > max_words:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_count = 0
            chunks.extend(
                " ".join(sentence_words[i : i + max_words])
                for i in range(0, sentence_count, max_words)
            )
            continue
        if current and current_count + sentence_count > max_words:
            chunks.append(" ".join(current))
            current = []
            current_count = 0
        current.append(sentence)
        current_count += sentence_count
    if current:
        chunks.append(" ".join(current))
    return chunks or [text]


def _windows(text: str, size: int, overlap: int) -> List[str]:
    words = text.split()
    if len(words) <= size:
        return [text]
    step = max(1, size - overlap)
    min_tail_words = max(1, int(size * 0.3))
    windows: List[str] = []
    for start in range(0, len(words), step):
        remaining = len(words) - start
        if windows and remaining < (min_tail_words + overlap):
            break
        windows.append(" ".join(words[start : start + size]))
    return windows
