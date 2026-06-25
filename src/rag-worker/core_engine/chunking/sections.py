"""Section split — đơn vị NGHĨA (heading-aware), KHÔNG token-chunk mù.

Bám ingestion.md §5: chia theo cấu trúc nghĩa của tác giả (heading); section quá
dài → sub-split (length guard) giữ thứ tự. parent_text = full content (đưa vào LLM
prompt / BM25); children = cửa sổ nhỏ để embed. Khớp `entities.Chunk`.

Không phụ thuộc AI — production thay bằng parser/splitter thật (MarkItDown →
section) qua cùng chữ ký, KHÔNG đổi engine.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class Section:
    section_title: str
    section_index: int        # page PDF thật (nếu có sentinel) hoặc thứ tự section
    parent_text: str          # full content -> LLM prompt
    children: List[str]       # sub-split để embed


# Sentinel trang do parser nhúng (PDF nhiều trang): <!--PG n-->. Chunker map section
# về trang thật rồi STRIP. Không có sentinel -> dùng bộ đếm section (hành vi cũ).
_PAGE_SENTINEL = re.compile(r"<!--PG (\d+)-->")
# Dòng bảng markdown: bắt đầu+kết thúc bằng `|`.
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")


def split_sections(
    markdown: str,
    parent_max_words: int,
    child_max_words: int,
    child_overlap_words: int,
) -> List[Section]:
    sections: List[Section] = []
    counter = 1
    for page_num, page_text in _split_by_page(markdown):
        for title, body in _split_by_heading(page_text):
            body = body.strip()
            if not body:
                continue
            index = page_num if page_num is not None else counter
            for kind, seg in _segment_tables(body):
                if kind == "table":
                    # Bảng = 1 Section: parent_text = cả bảng (cho LLM); children mang
                    # header lặp lại để mỗi chunk tự biết tên cột.
                    sections.append(
                        Section(
                            section_title=title or "(no heading)",
                            section_index=index,
                            parent_text=seg,
                            children=_table_children(seg, child_max_words),
                        )
                    )
                else:
                    for parent_text in _cap_words(seg, parent_max_words):
                        children = _windows(parent_text, child_max_words, child_overlap_words)
                        sections.append(
                            Section(
                                section_title=title or "(no heading)",
                                section_index=index,
                                parent_text=parent_text,
                                children=children or [parent_text],
                            )
                        )
            counter += 1
    return _dedup_children(sections)


def _split_by_page(markdown: str) -> List[Tuple[Optional[int], str]]:
    """Tách theo sentinel trang `<!--PG n-->` (parser nhúng cho PDF nhiều trang).

    Trả [(page_num, text)] với sentinel ĐÃ strip. Không có sentinel -> [(None, all)]
    (giữ hành vi cũ: chunker dùng bộ đếm section thay số trang).
    """
    matches = list(_PAGE_SENTINEL.finditer(markdown))
    if not matches:
        return [(None, markdown)]
    pages: List[Tuple[Optional[int], str]] = []
    for idx, m in enumerate(matches):
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        text = markdown[start:end].strip()
        if text:
            pages.append((int(m.group(1)), text))
    return pages or [(None, markdown)]


def _segment_tables(body: str) -> List[Tuple[str, str]]:
    """Tách body thành đoạn xen kẽ ("prose", text) / ("table", text).

    Run ≥2 dòng bảng liên tiếp = "table" (giữ nguyên để không cắt header ↔ dữ liệu).
    Dòng bảng lẻ loi -> coi như prose.
    """
    lines = body.split("\n")
    segments: List[Tuple[str, str]] = []
    buf: List[str] = []
    i, n = 0, len(lines)
    while i < n:
        if _TABLE_LINE.match(lines[i]):
            j = i
            while j < n and _TABLE_LINE.match(lines[j]):
                j += 1
            run = lines[i:j]
            if len(run) >= 2:
                if buf:
                    segments.append(("prose", "\n".join(buf)))
                    buf = []
                segments.append(("table", "\n".join(run)))
            else:
                buf.extend(run)
            i = j
        else:
            buf.append(lines[i])
            i += 1
    if buf:
        segments.append(("prose", "\n".join(buf)))
    return segments or [("prose", body)]


def _is_separator_row(line: str) -> bool:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{1,}:?", c or "") for c in cells)


def _table_children(table_text: str, child_max_words: int) -> List[str]:
    """Chia bảng theo NHÓM DÒNG, lặp 2 dòng header (header + `---`) vào mỗi chunk.

    Bảng nhỏ (≤ child_max_words) -> 1 chunk cả bảng. Bảng lớn -> mỗi chunk = header
    + nhóm dòng dữ liệu sao cho ~child_max_words từ. Mỗi chunk tự mang tên cột.
    """
    lines = [ln for ln in table_text.split("\n") if ln.strip()]
    if len(lines) <= 1 or len(table_text.split()) <= child_max_words:
        return [table_text]
    header = [lines[0]]
    body_start = 1
    if len(lines) >= 2 and _is_separator_row(lines[1]):
        header.append(lines[1])
        body_start = 2
    data = lines[body_start:]
    if not data:
        return [table_text]
    header_words = sum(len(h.split()) for h in header)
    children: List[str] = []
    cur: List[str] = []
    cur_words = header_words
    for row in data:
        rw = len(row.split())
        if cur and cur_words + rw > child_max_words:
            children.append("\n".join(header + cur))
            cur = []
            cur_words = header_words
        cur.append(row)
        cur_words += rw
    if cur:
        children.append("\n".join(header + cur))
    return children or [table_text]


def _dedup_children(sections: List[Section]) -> List[Section]:
    """Loại bỏ children trùng nội dung (hash MD5) xuyên suốt document.

    Sliding window overlap + trang bìa lặp lại tạo ra nhiều chunk giống nhau
    → dedup giữ lại chunk đầu tiên gặp, bỏ các bản sao. Section rỗng sau dedup
    bị loại (không còn children nào mới).
    """
    seen: set[str] = set()
    result: List[Section] = []
    for s in sections:
        unique = [
            child for child in s.children
            if (h := hashlib.md5(child.strip().encode()).hexdigest()) not in seen
            and not seen.add(h)  # type: ignore[func-returns-value]
        ]
        if unique:
            result.append(Section(s.section_title, s.section_index, s.parent_text, unique))
    return result


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
    """Cửa sổ trượt SENTENCE-AWARE: gom theo CÂU tới ~size từ, overlap lùi câu cuối.

    Câu đơn dài hơn size -> giữ nguyên (KHÔNG cắt giữa câu). Text không có ranh giới
    câu (vd dãy số, token rời) -> rơi về cửa sổ theo SỐ TỪ (hành vi cũ, giữ test gác).
    """
    words = text.split()
    if len(words) <= size:
        return [text]
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    if len(sentences) <= 1:
        return _word_windows(words, size, overlap)
    sent_words = [len(s.split()) for s in sentences]
    windows: List[str] = []
    i, n = 0, len(sentences)
    while i < n:
        cur: List[str] = []
        cur_w = 0
        j = i
        while j < n and (not cur or cur_w + sent_words[j] <= size):
            cur.append(sentences[j])
            cur_w += sent_words[j]
            j += 1
        windows.append(" ".join(cur))
        if j >= n:
            break
        # overlap: lùi lại các câu cuối tới khi đủ ~overlap từ (đảm bảo TIẾN: next_i > i).
        back_w = 0
        k = j - 1
        while k > i and back_w < overlap:
            back_w += sent_words[k]
            k -= 1
        i = k + 1
    return windows


def _word_windows(words: List[str], size: int, overlap: int) -> List[str]:
    """Cửa sổ theo SỐ TỪ (hành vi cũ) — dùng khi text không có ranh giới câu."""
    if len(words) <= size:
        return [" ".join(words)]
    step = max(1, size - overlap)
    min_tail_words = max(1, int(size * 0.3))
    windows: List[str] = []
    for start in range(0, len(words), step):
        remaining = len(words) - start
        if windows and remaining < (min_tail_words + overlap):
            break
        windows.append(" ".join(words[start : start + size]))
    return windows
