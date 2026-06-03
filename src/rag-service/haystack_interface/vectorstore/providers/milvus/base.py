"""Phần dùng chung cho hai deployment của provider `milvus`.

`remote.py` (AsyncMilvusClient, async thuần) và `inprocess.py` (MilvusClient + Milvus
Lite, sync + to_thread) chia sẻ: map record→row, ráp kết quả search + POST-FILTER
`can_access`. Toàn bộ payload nằm trong MỘT field động `payload` (JSON) nên không cần
khai báo schema cứng; collection tạo bằng quick-setup (id + vector COSINE).

base KHÔNG import pymilvus — phần thuần dữ liệu; client do từng file deployment nạp.
"""

from __future__ import annotations

from typing import Sequence

from app.domain.repositories.vector_repository import SearchResult, UserContext

from haystack_interface.access import can_access
from haystack_interface.vectorstore.config import VectorStoreConfig
from haystack_interface.vectorstore.provider import VectorStoreProvider
from haystack_interface.vectorstore.types import VectorRecord

PK = "id"
VECTOR = "vector"
PAYLOAD = "payload"
OVERFETCH = 5


class MilvusBase(VectorStoreProvider):
    def __init__(self, config: VectorStoreConfig | None = None):
        super().__init__(config or VectorStoreConfig(provider="milvus"))

    @property
    def collection_name(self) -> str:
        return self.config.index_id()

    def _row(self, record: VectorRecord) -> dict:
        if len(record.vector) != self.config.dimension:
            raise ValueError(
                f"Sai dimension: vector={len(record.vector)} != index={self.config.dimension}. "
                "Doi dimension la migration (ingestion.md §8)."
            )
        return {
            PK: record.chunk_id,
            VECTOR: list(record.vector),
            PAYLOAD: {**dict(record.payload), "chunk_id": record.chunk_id},
        }

    @staticmethod
    def _dup_id(existing) -> str | None:
        ids = sorted(row.get(PK) for row in (existing or []) if row.get(PK))
        return ids[0] if ids else None

    def _assemble(self, hits, user_context: UserContext, top_k: int) -> list[SearchResult]:
        out: list[SearchResult] = []
        for hit in hits or []:
            entity = hit.get("entity", hit) if isinstance(hit, dict) else {}
            payload = entity.get(PAYLOAD, {}) or {}
            if not can_access(payload, user_context):
                continue
            distance = hit.get("distance") if isinstance(hit, dict) else None
            out.append(self._to_result(payload, distance))
            if len(out) >= top_k:
                break
        return out

    @staticmethod
    def _to_result(m: dict, distance) -> SearchResult:
        # COSINE trong Milvus: score càng cao càng gần (đã là similarity).
        score = float(distance) if distance is not None else 0.0
        return SearchResult(
            chunk_id=m.get("chunk_id", ""),
            parent_id=m.get("parent_id", ""),
            document_id=m.get("document_id", ""),
            document_name=m.get("document_name", ""),
            file_type=m.get("file_type", ""),
            page_number=int(m.get("page_number", 0)),
            section_title=m.get("section_title", ""),
            child_text=m.get("child_text", ""),
            parent_text=m.get("parent_text", ""),
            score=score,
            rerank_score=float(m.get("rerank_score", 0.0)),
        )

    @staticmethod
    def _doc_filter(document_id: str) -> str:
        escaped = document_id.replace('"', '\\"')
        return f'{PAYLOAD}["document_id"] == "{escaped}"'

    def _create_kwargs(self) -> dict:
        return {
            "collection_name": self.collection_name,
            "dimension": self.config.dimension,
            "metric_type": "COSINE",
            "id_type": "string",
            "max_length": 512,
            "auto_id": False,
        }

    def _search_kwargs(self, vector: Sequence[float], top_k: int) -> dict:
        return {
            "collection_name": self.collection_name,
            "data": [list(vector)],
            "limit": top_k * OVERFETCH,
            "output_fields": [PAYLOAD],
            "search_params": {"metric_type": "COSINE"},
        }
