"""AdaptiveConcurrencyLimiter — AIMD elastic concurrency cho phía feeder.

Mirror triết lý selector `adaptive_balanced` của AI Router: thay vì cap CỨNG số
inflight, ta TỰ DÒ trần. Trần dưới (AI Router: multi-key/multi-model AIMD) co giãn
được, nên feeder cũng nên co giãn — nếu để semaphore tĩnh thì feeder thành nút cổ
chai dù router còn gánh được.

Vì sao KHÔNG dùng `asyncio.Semaphore`: semaphore không resize được sau khi tạo. Ở
đây limit thay đổi runtime (AIMD), nên dùng `asyncio.Condition` + bộ đếm `_active`:
acquire chờ khi `_active >= _limit`, release giảm `_active` rồi notify waiter.

AIMD:
- Additive increase: sau `grow_after_successes` lần release THÀNH CÔNG liên tiếp →
  `limit += 1` (bounded max), reset streak.
- Multiplicative decrease: khi release do `TransientAIError` (provider 429/overload)
  → `limit = max(min, int(limit * shrink_factor))`, reset streak.

Lỗi VẪN surface: limiter chỉ quan sát exception để chỉnh limit RỒI re-raise — không
nuốt. Exception KHÔNG phải TransientAIError không được coi là tín hiệu overload (không
shrink, cũng không tính là success) để khỏi co trần oan vì bug logic/permanent error.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Optional

import asyncio

from core_engine.ai.base import TransientAIError

OnResize = Callable[[str, int], None]


class AdaptiveConcurrencyLimiter:
    """Elastic concurrency gate (AIMD). 1 event loop, đồng bộ qua Condition.

    Dùng:
        async with limiter.slot():
            await call_vision(...)   # TransientAIError ở đây -> shrink rồi re-raise
    """

    def __init__(
        self,
        *,
        initial: int,
        min_limit: int,
        max_limit: int,
        grow_after_successes: int = 3,
        shrink_factor: float = 0.5,
        on_resize: Optional[OnResize] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if min_limit < 1:
            raise ValueError("min_limit must be >= 1")
        if max_limit < min_limit:
            raise ValueError("max_limit must be >= min_limit")
        if grow_after_successes < 1:
            raise ValueError("grow_after_successes must be >= 1")
        if not (0.0 < shrink_factor < 1.0):
            raise ValueError("shrink_factor must be in (0, 1)")

        self._min = min_limit
        self._max = max_limit
        # Clamp initial vào [min, max] — caller đọc env có thể lệch biên.
        self._limit = max(min_limit, min(max_limit, initial))
        self._grow_after = grow_after_successes
        self._shrink_factor = shrink_factor
        self._on_resize = on_resize
        self._logger = logger or logging.getLogger(__name__)

        self._active = 0
        self._success_streak = 0
        self._cond = asyncio.Condition()

    @property
    def limit(self) -> int:
        """Trần hiện tại (đọc cho test/log)."""
        return self._limit

    @property
    def active(self) -> int:
        """Số slot đang chiếm (đọc cho test/log)."""
        return self._active

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        await self._acquire()
        # Ba kết cục: "success" (thoát sạch) | "transient" (overload -> shrink) |
        # "other" (exception khác -> KHÔNG shrink, cũng KHÔNG tính success).
        outcome = "other"
        try:
            yield
            outcome = "success"
        except TransientAIError:
            outcome = "transient"
            raise
        finally:
            await self._release(outcome)

    async def _acquire(self) -> None:
        async with self._cond:
            # `while` (không `if`): tránh spurious/thua-race khi nhiều waiter cùng dậy.
            while self._active >= self._limit:
                await self._cond.wait()
            self._active += 1

    async def _release(self, outcome: str) -> None:
        async with self._cond:
            self._active -= 1
            if outcome == "transient":
                self._shrink_locked()
            elif outcome == "success":
                self._maybe_grow_locked()
            # outcome == "other": không tín hiệu provider -> không grow/shrink, streak giữ.
            # Đánh thức waiter: grow có thể mở thêm slot, release luôn nhả 1 slot.
            self._cond.notify_all()

    def _maybe_grow_locked(self) -> None:
        self._success_streak += 1
        if self._success_streak < self._grow_after:
            return
        self._success_streak = 0
        if self._limit < self._max:
            self._limit += 1
            self._emit("grow")

    def _shrink_locked(self) -> None:
        self._success_streak = 0
        new_limit = max(self._min, int(self._limit * self._shrink_factor))
        if new_limit < self._limit:
            self._limit = new_limit
            self._emit("shrink")

    def _emit(self, event: str) -> None:
        if self._on_resize is None:
            return
        try:
            self._on_resize(event, self._limit)
        except Exception:  # callback không được làm sập feeder
            self._logger.debug("adaptive_limiter on_resize callback failed", exc_info=True)
