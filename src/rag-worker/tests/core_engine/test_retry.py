from __future__ import annotations

import pytest

from core_engine.ai.base import PermanentAIError, TransientAIError, retry_async


@pytest.mark.asyncio
async def test_retry_async_retries_transient_errors_until_success() -> None:
    attempts = {"count": 0}

    async def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TransientAIError("retry")
        return "ok"

    result = await retry_async(flaky, max_retries=5, base_delay=0.001)

    assert result == "ok"
    assert attempts["count"] == 3


@pytest.mark.asyncio
async def test_retry_async_does_not_retry_permanent_errors() -> None:
    attempts = {"count": 0}

    async def permanent():
        attempts["count"] += 1
        raise PermanentAIError("bad request")

    with pytest.raises(PermanentAIError):
        await retry_async(permanent, max_retries=5, base_delay=0.001)

    assert attempts["count"] == 1
