from __future__ import annotations

import importlib.metadata

import pytest

from core_engine.registry import Registry


def test_register_get_available() -> None:
    reg: Registry[str] = Registry("widget")
    reg.register("alpha", "A")
    reg.register("Beta", "B")  # case-insensitive key
    assert reg.get("alpha") == "A"
    assert reg.get("BETA") == "B"
    assert reg.available() == ["alpha", "beta"]


def test_duplicate_name_guarded_unless_override() -> None:
    reg: Registry[str] = Registry("widget")
    reg.register("alpha", "A")
    with pytest.raises(ValueError):
        reg.register("alpha", "A2")
    reg.register("alpha", "A2", override=True)
    assert reg.get("alpha") == "A2"


def test_unknown_name_lists_available() -> None:
    reg: Registry[str] = Registry("provider")
    reg.register("qdrant", "Q")
    with pytest.raises(ValueError) as exc:
        reg.get("khong_ton_tai")
    # Contract đang được selftest_vectorstore dựa vào: chuỗi 'chua dang ky' + danh sách.
    assert "chua dang ky" in str(exc.value)
    assert "qdrant" in str(exc.value)


class _FakeEntryPoint:
    def __init__(self, name: str, value: str) -> None:
        self.name = name
        self._value = value

    def load(self) -> str:
        return self._value


def test_entry_point_discovery_without_import_side_effect(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_entry_points(*, group: str):
        captured["group"] = group
        return [_FakeEntryPoint("plugin_db", "PLUGIN")]

    monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)

    reg: Registry[str] = Registry("provider", entry_point_group="rag_worker.vector_store")
    # Chưa ai import module của plugin; discovery qua entry-point lúc get/available.
    assert reg.get("plugin_db") == "PLUGIN"
    assert captured["group"] == "rag_worker.vector_store"


def test_builtin_wins_over_entry_point_on_name_clash(monkeypatch) -> None:
    def fake_entry_points(*, group: str):
        return [_FakeEntryPoint("qdrant", "FROM_ENTRY_POINT")]

    monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)

    reg: Registry[str] = Registry("provider", entry_point_group="rag_worker.vector_store")
    reg.register("qdrant", "BUILTIN")  # built-in đăng ký tường minh lúc import
    assert reg.get("qdrant") == "BUILTIN"  # entry-point KHÔNG đè built-in


def test_no_group_skips_entry_point_lookup(monkeypatch) -> None:
    called = {"n": 0}

    def fake_entry_points(*, group: str):
        called["n"] += 1
        return []

    monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)

    reg: Registry[str] = Registry("widget")  # ko entry_point_group
    reg.register("alpha", "A")
    assert reg.available() == ["alpha"]
    assert called["n"] == 0  # ko group -> ko gọi entry_points
