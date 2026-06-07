from __future__ import annotations

import pytest

from app.interfaces.api.runtime import validate_ingest_runtime_limits


def test_store_reconcile_requires_bucket_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_RECONCILE_ENABLED", "1")
    monkeypatch.setenv("STORE_RECONCILE_INTERVAL_SECONDS", "900")
    monkeypatch.setenv("STORE_RECONCILE_MIN_AGE_SECONDS", "60")
    monkeypatch.delenv("S3_SOURCE_BUCKET", raising=False)
    monkeypatch.delenv("R2_BUCKET", raising=False)

    with pytest.raises(ValueError, match="STORE_RECONCILE requires"):
        validate_ingest_runtime_limits()


def test_store_reconcile_accepts_valid_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_RECONCILE_ENABLED", "1")
    monkeypatch.setenv("STORE_RECONCILE_INTERVAL_SECONDS", "900")
    monkeypatch.setenv("STORE_RECONCILE_MIN_AGE_SECONDS", "60")
    monkeypatch.setenv("S3_SOURCE_BUCKET", "docs")

    validate_ingest_runtime_limits()
