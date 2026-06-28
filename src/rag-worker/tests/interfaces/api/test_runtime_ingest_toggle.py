from __future__ import annotations

import pytest

from app.interfaces.api import runtime as runtime_module
from app.interfaces.api.runtime import (
    ingest_enabled_from_env,
    validate_ingest_runtime_limits,
)


def test_ingest_enabled_defaults_true_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INGEST_ENABLED", raising=False)
    assert ingest_enabled_from_env() is True


@pytest.mark.parametrize("raw", ["false", "0", "no", "off", "FALSE", " Off "])
def test_ingest_enabled_false_values(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("INGEST_ENABLED", raw)
    assert ingest_enabled_from_env() is False


@pytest.mark.parametrize("raw", ["true", "1", "yes", "on", "TRUE", " On "])
def test_ingest_enabled_true_values(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("INGEST_ENABLED", raw)
    assert ingest_enabled_from_env() is True


def test_validate_skips_worker_count_when_ingest_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # INGEST_ENABLED=false: INGEST_WORKER_COUNT<=0 KHÔNG được raise (search-only
    # instance không spawn ingest-worker nên không validate count).
    monkeypatch.setenv("INGEST_ENABLED", "false")
    monkeypatch.setenv("INGEST_WORKER_COUNT", "0")
    validate_ingest_runtime_limits()  # phải không raise


def test_validate_enforces_worker_count_when_ingest_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INGEST_ENABLED", "true")
    monkeypatch.setenv("INGEST_WORKER_COUNT", "0")
    with pytest.raises(ValueError, match="INGEST_WORKER_COUNT must be > 0"):
        validate_ingest_runtime_limits()


def test_runtime_exposes_ingest_helper() -> None:
    # Helper tồn tại + tham chiếu trong module (bảo vệ khỏi xóa nhầm).
    assert callable(runtime_module.ingest_enabled_from_env)
