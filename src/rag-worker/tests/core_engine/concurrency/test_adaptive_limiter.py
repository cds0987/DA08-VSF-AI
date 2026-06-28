"""Unit test cho AdaptiveConcurrencyLimiter (AIMD elastic). Thuần, không provider thật."""

from __future__ import annotations

import asyncio

import pytest

from core_engine.ai.base import TransientAIError
from core_engine.concurrency import AdaptiveConcurrencyLimiter


def _make(**kw) -> AdaptiveConcurrencyLimiter:
    base = dict(initial=2, min_limit=2, max_limit=6, grow_after_successes=3, shrink_factor=0.5)
    base.update(kw)
    return AdaptiveConcurrencyLimiter(**base)


async def _ok_slot(limiter: AdaptiveConcurrencyLimiter) -> None:
    async with limiter.slot():
        pass


def test_clamp_initial_into_range() -> None:
    assert _make(initial=99).limit == 6      # > max -> max
    assert _make(initial=0).limit == 2       # < min -> min
    assert _make(initial=4).limit == 4       # trong khoảng -> giữ


async def test_additive_increase_up_to_max() -> None:
    events: list[tuple[str, int]] = []
    limiter = _make(initial=2, on_resize=lambda e, l: events.append((e, l)))

    # grow_after_successes=3: cứ 3 success liên tiếp +1, không vượt max=6.
    for _ in range(3 * 20):
        await _ok_slot(limiter)

    assert limiter.limit == 6
    assert all(e == "grow" for e, _ in events)
    assert [l for _, l in events] == [3, 4, 5, 6]   # dừng ở max, không phát thêm


async def test_multiplicative_decrease_not_below_min() -> None:
    limiter = _make(initial=6, min_limit=2, max_limit=6)

    async def boom() -> None:
        async with limiter.slot():
            raise TransientAIError("429")

    with pytest.raises(TransientAIError):
        await boom()
    assert limiter.limit == 3                 # int(6 * 0.5)

    with pytest.raises(TransientAIError):
        await boom()
    assert limiter.limit == 2                 # int(3 * 0.5)=1 -> clamp lên min=2

    with pytest.raises(TransientAIError):
        await boom()
    assert limiter.limit == 2                 # đã ở min, không tụt thêm


async def test_transient_resets_success_streak() -> None:
    limiter = _make(initial=2, grow_after_successes=3)

    await _ok_slot(limiter)
    await _ok_slot(limiter)                   # streak=2, chưa grow

    async def boom() -> None:
        async with limiter.slot():
            raise TransientAIError("429")

    with pytest.raises(TransientAIError):
        await boom()                          # reset streak

    await _ok_slot(limiter)
    await _ok_slot(limiter)
    assert limiter.limit == 2                 # mới 2 success sau reset -> chưa grow


async def test_concurrency_gate_never_exceeds_limit() -> None:
    limiter = _make(initial=3, min_limit=3, max_limit=3)   # cố định 3
    active = 0
    peak = 0
    release = asyncio.Event()

    async def worker() -> None:
        nonlocal active, peak
        async with limiter.slot():
            active += 1
            peak = max(peak, active)
            await release.wait()
            active -= 1

    tasks = [asyncio.create_task(worker()) for _ in range(10)]
    # Cho các task chạy tới điểm chờ; chỉ 3 task được vào slot.
    await asyncio.sleep(0.05)
    assert active == 3
    assert peak == 3

    release.set()
    await asyncio.gather(*tasks)
    assert peak == 3


async def test_release_admits_waiter() -> None:
    limiter = _make(initial=1, min_limit=1, max_limit=1)
    order: list[str] = []
    first_in = asyncio.Event()
    let_first_go = asyncio.Event()

    async def first() -> None:
        async with limiter.slot():
            order.append("first-in")
            first_in.set()
            await let_first_go.wait()
        order.append("first-out")

    async def second() -> None:
        await first_in.wait()                 # đảm bảo first chiếm slot trước
        async with limiter.slot():
            order.append("second-in")

    t1 = asyncio.create_task(first())
    t2 = asyncio.create_task(second())
    await first_in.wait()
    await asyncio.sleep(0.01)
    assert "second-in" not in order           # second bị chặn khi limit=1 đang đầy

    let_first_go.set()
    await asyncio.gather(t1, t2)
    assert order == ["first-in", "first-out", "second-in"]


async def test_reraises_transient_and_other_exceptions() -> None:
    limiter = _make()

    async def transient() -> None:
        async with limiter.slot():
            raise TransientAIError("boom")

    async def other() -> None:
        async with limiter.slot():
            raise RuntimeError("boom")

    with pytest.raises(TransientAIError):
        await transient()
    with pytest.raises(RuntimeError):
        await other()


async def test_non_transient_error_does_not_shrink_or_grow() -> None:
    limiter = _make(initial=4, grow_after_successes=1)

    async def other() -> None:
        async with limiter.slot():
            raise RuntimeError("logic bug")

    for _ in range(5):
        with pytest.raises(RuntimeError):
            await other()
    # KHÔNG shrink (không phải overload) và KHÔNG tính success: grow_after=1 nhưng
    # 5 lần "other" vẫn để limit nguyên 4.
    assert limiter.limit == 4
    assert limiter.active == 0
