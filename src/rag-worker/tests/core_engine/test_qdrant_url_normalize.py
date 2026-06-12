from __future__ import annotations

import base64

import pytest

from core_engine.vectorstore.config import (
    VectorStoreConfig,
    basic_auth_header,
    normalize_remote_qdrant_url,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Cloud Run https thiếu port -> thêm :443 (nếu không qdrant-client rớt về 6333).
        (
            "https://qdrant-289299478169.asia-southeast1.run.app",
            "https://qdrant-289299478169.asia-southeast1.run.app:443",
        ),
        # Idempotent: đã có :443 thì giữ nguyên.
        (
            "https://qdrant.example.run.app:443",
            "https://qdrant.example.run.app:443",
        ),
        # Trailing slash vẫn chèn port đúng vị trí netloc.
        (
            "https://qdrant.example.run.app/",
            "https://qdrant.example.run.app:443/",
        ),
        # http self-hosted / local có port -> không đụng tới.
        ("http://localhost:6333", "http://localhost:6333"),
        ("http://qdrant:6333", "http://qdrant:6333"),
        # Rỗng -> trả nguyên (deployment in_process).
        ("", ""),
    ],
)
def test_normalize_remote_url(raw: str, expected: str) -> None:
    assert normalize_remote_qdrant_url(raw) == expected


def test_remote_client_kwargs_normalizes_url_and_sets_timeout() -> None:
    cfg = VectorStoreConfig(
        url="https://qdrant.example.run.app",
        api_key="secret",
    )
    kwargs = cfg.remote_client_kwargs()
    assert kwargs["url"] == "https://qdrant.example.run.app:443"
    assert kwargs["api_key"] == "secret"
    assert kwargs["timeout"] == 30


def test_remote_client_kwargs_timeout_env_override(monkeypatch) -> None:
    monkeypatch.setenv("QDRANT_TIMEOUT", "75")
    kwargs = VectorStoreConfig(url="https://q.run.app").remote_client_kwargs()
    assert kwargs["timeout"] == 75
    assert kwargs["api_key"] is None


@pytest.mark.parametrize(
    "creds, expected",
    [
        ("qdrantteam:123", "Basic " + base64.b64encode(b"qdrantteam:123").decode()),
        ("", ""),
        ("nocolon", ""),  # thiếu ':' -> không phải user:pass hợp lệ
    ],
)
def test_basic_auth_header(creds: str, expected: str) -> None:
    assert basic_auth_header(creds) == expected


def test_remote_client_kwargs_injects_basic_auth_header() -> None:
    # Qdrant sau nginx Basic Auth (http port 80) -> header Authorization Basic.
    cfg = VectorStoreConfig(url="http://10.0.0.1:80", basic_auth="qdrantteam:123")
    kwargs = cfg.remote_client_kwargs()
    assert kwargs["url"] == "http://10.0.0.1:80"
    assert kwargs["headers"]["Authorization"] == basic_auth_header("qdrantteam:123")


def test_remote_client_kwargs_no_basic_auth_no_headers() -> None:
    kwargs = VectorStoreConfig(url="https://q.run.app").remote_client_kwargs()
    assert "headers" not in kwargs
