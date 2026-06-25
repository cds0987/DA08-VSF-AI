from core_engine.chunking.sections import _cap_words, _windows, split_sections


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
