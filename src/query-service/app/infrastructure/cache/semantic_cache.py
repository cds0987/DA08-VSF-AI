from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import re


TOKEN_PATTERN = re.compile(r"[\wÀ-ỹ]+", re.UNICODE)


@dataclass
class SemanticCacheEntry:
    namespace: str
    question: str
    answer: str
    sources: list[dict]
    vector: dict[str, float]
    expires_at: datetime


class InMemorySemanticCache:
    def __init__(self, ttl_seconds: int, threshold: float) -> None:
        self._ttl = ttl_seconds
        self._threshold = threshold
        self._entries: list[SemanticCacheEntry] = []

    async def get(self, namespace: str, question: str) -> tuple[str, list[dict]] | None:
        now = datetime.now(timezone.utc)
        self._entries = [entry for entry in self._entries if entry.expires_at > now]
        vector = self._vectorize(question)
        for entry in self._entries:
            if entry.namespace != namespace:
                continue
            if self._cosine(vector, entry.vector) >= self._threshold:
                return entry.answer, entry.sources
        return None

    async def put(self, namespace: str, question: str, answer: str, sources: list[dict]) -> None:
        self._entries.append(
            SemanticCacheEntry(
                namespace=namespace,
                question=question,
                answer=answer,
                sources=sources,
                vector=self._vectorize(question),
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=self._ttl),
            )
        )

    def reset(self) -> None:
        self._entries.clear()

    @staticmethod
    def _vectorize(text: str) -> dict[str, float]:
        vector: dict[str, float] = {}
        for token in TOKEN_PATTERN.findall(text.lower()):
            vector[token] = vector.get(token, 0.0) + 1.0
        return vector

    @staticmethod
    def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        dot = sum(value * right.get(token, 0.0) for token, value in left.items())
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)
