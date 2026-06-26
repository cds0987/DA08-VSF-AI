"""Unit test cho helper gom "suy nghĩ của agent" để lưu kèm message (sống qua reload)."""

from app.application.use_cases.query.orchestration import (
    _accumulate_agent_meta,
    _build_agent_meta,
)


def _run(events: list[dict]):
    thoughts: list[dict] = []
    models: list[dict] = []
    trace: list[dict] = []
    for ev in events:
        _accumulate_agent_meta(ev, thoughts, models, trace)
    return thoughts, models, trace


def test_thought_tokens_same_node_are_glued():
    thoughts, _, _ = _run([
        {"phase": "thought", "node": "verify", "text": "Đang "},
        {"phase": "thought", "node": "verify", "text": "kiểm tra"},
        {"phase": "thought", "node": "answer", "text": "Soạn đáp án"},
    ])
    assert thoughts == [
        {"node": "verify", "text": "Đang kiểm tra"},
        {"node": "answer", "text": "Soạn đáp án"},
    ]


def test_models_deduped():
    _, models, _ = _run([
        {"phase": "model_used", "node": "plan", "model": "gpt-5.4-mini"},
        {"phase": "model_used", "node": "plan", "model": "gpt-5.4-mini"},
        {"phase": "model_used", "node": "answer", "model": "deepseek"},
    ])
    assert models == [
        {"node": "plan", "model": "gpt-5.4-mini"},
        {"node": "answer", "model": "deepseek"},
    ]


def test_acting_observing_pairs_into_one_trace_step():
    _, _, trace = _run([
        {"phase": "acting", "tool": "rag_search", "tool_args": {"q": "lương"}, "iterations": 1},
        {"phase": "observing", "tool": "rag_search", "tool_result_summary": {"count": 3, "docs": ["a"], "raw": "X" * 9999}},
    ])
    assert len(trace) == 1
    e = trace[0]
    assert e["tool"] == "rag_search"
    assert e["resultCount"] == 3
    assert e["resultDocs"] == ["a"]
    assert e["pending"] is False
    assert "resultRaw" not in e  # raw lớn -> không lưu


def test_build_agent_meta_only_includes_nonempty_and_strips_pending():
    meta = _build_agent_meta(
        thoughts=[{"node": "verify", "text": "x"}],
        plan={"route": "light", "steps": [{"id": 1, "status": "ok"}]},
        trace=[{"tool": "rag", "pending": True}],
        models=[],
    )
    assert "thoughts" in meta and "plan" in meta and "trace" in meta
    assert "models" not in meta            # rỗng -> bỏ
    assert "pending" not in meta["trace"][0]  # cờ pending bị tước


def test_build_agent_meta_empty_returns_empty_dict():
    assert _build_agent_meta([], None, [], []) == {}
