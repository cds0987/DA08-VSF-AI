from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta


class InMemoryRateLimiter:
    def __init__(self, max_requests_per_minute: int) -> None:
        self._max = max_requests_per_minute
        self._hits: dict[str, deque[datetime]] = defaultdict(deque)

    def allow(self, user_id: str) -> bool:
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=60)
        hits = self._hits[user_id]
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= self._max:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()
