from core_engine.chunking.sections import _cap_words, _windows, split_sections


# ---------------------------------------------------------------- sentence-aware windows
def test_windows_respects_sentence_boundaries() -> None:
    # 6 câu, mỗi câu 10 từ kết thúc bằng "." → window gom theo CÂU, không cắt giữa câu.
    sentences = [f"S{i} " + " ".join(f"w{i}_{k}" for k in range(8)) + "." for i in range(6)]
    text = " ".join(sentences)
    windows = _windows(text, 25, 5)
    assert len(windows) > 1
    for w in windows:
        assert w.rstrip().endswith("."), f"window cắt giữa câu: {w!r}"


# ----------------------------------------------------------------------- table-aware
def test_table_small_kept_as_single_chunk() -> None:
    table = "| Phòng | Số người |\n| --- | --- |\n| HR | 12 |\n| IT | 30 |"
    sections = split_sections("# Headcount\n" + table, parent_max_words=220,
                              child_max_words=90, child_overlap_words=15)
    tbl = [s for s in sections if "Phòng" in s.parent_text]
    assert len(tbl) == 1
    assert len(tbl[0].children) == 1
    assert "Phòng" in tbl[0].children[0] and "HR" in tbl[0].children[0]


def test_table_large_each_chunk_carries_header() -> None:
    header = "| Phòng | Số người |\n| --- | --- |"
    rows = "\n".join(f"| Dept{i} | {i * 3} |" for i in range(40))
    sections = split_sections("# Headcount\n" + header + "\n" + rows,
                              parent_max_words=220, child_max_words=20, child_overlap_words=5)
    tbl = [s for s in sections if "Phòng" in s.parent_text][0]
    assert len(tbl.children) > 1
    for c in tbl.children:
        assert "Phòng" in c and "Số người" in c, f"chunk thiếu header: {c!r}"


# ------------------------------------------------------------------ page sentinel (#3)
def test_page_sentinel_maps_real_page_and_strips() -> None:
    md = "<!--PG 3-->\nNội dung trang ba ở đây.\n\n<!--PG 7-->\nNội dung trang bảy ở đây."
    sections = split_sections(md, parent_max_words=220, child_max_words=90, child_overlap_words=15)
    assert {s.section_index for s in sections} == {3, 7}
    for s in sections:
        assert "<!--PG" not in s.parent_text
        for c in s.children:
            assert "<!--PG" not in c


def test_cap_words_prefers_sentence_boundaries() -> None:
    text = "One two three. Four five six. Seven eight nine."

    chunks = _cap_words(text, 4)

    assert chunks == ["One two three.", "Four five six.", "Seven eight nine."]


def test_windows_merges_tiny_tail_into_previous_window() -> None:
    text = " ".join(f"w{i}" for i in range(95))

    windows = _windows(text, 90, 15)

    assert len(windows) == 1
    assert windows[0].split()[0] == "w0"
    assert len(windows[0].split()) == 90


def test_dedup_removes_identical_children() -> None:
    # Trang bìa lặp lại nhiều lần (simulate DOCX không có heading → 1 block lớn → overlap)
    # Tạo markdown không có heading → split_sections tạo 1 section → sliding window
    # Dùng text đủ dài để tạo nhiều window overlap
    words = " ".join(f"word{i}" for i in range(200))
    sections = split_sections(words, parent_max_words=220, child_max_words=90, child_overlap_words=60)
    # Thu thập tất cả children
    all_children = [c for s in sections for c in s.children]
    # Kiểm tra không có duplicate
    assert len(all_children) == len(set(all_children)), "Có children trùng nhau sau dedup"


def test_dedup_across_repeated_cover_page() -> None:
    # Simulate: trang bìa xuất hiện 3 lần trong markdown (như DOCX bị parse trùng)
    cover = " ".join(f"cover{i}" for i in range(50))
    markdown = f"# Section 1\n{cover}\n\n# Section 2\n{cover}\n\n# Section 3\n{cover}"
    sections = split_sections(markdown, parent_max_words=220, child_max_words=90, child_overlap_words=15)
    all_children = [c for s in sections for c in s.children]
    unique_children = list(dict.fromkeys(all_children))
    assert len(all_children) == len(unique_children), "Chunk trang bìa bị lặp không được dedup"
