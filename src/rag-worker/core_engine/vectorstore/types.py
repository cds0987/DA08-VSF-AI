from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class VectorRecord:
    chunk_id: str
    vector: Sequence[float]
    payload: Mapping[str, Any]
