from __future__ import annotations

import pytest

pytest.importorskip("qdrant_client")

from core_engine.vectorstore.providers.qdrant.remote import _normalize_remote_url


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
    assert _normalize_remote_url(raw) == expected
