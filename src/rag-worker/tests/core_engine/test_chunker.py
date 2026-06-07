from core_engine.chunking.sections import _cap_words, _windows


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
