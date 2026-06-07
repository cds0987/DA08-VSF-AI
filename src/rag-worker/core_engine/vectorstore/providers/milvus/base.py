"""Phần dùng chung cho hai deployment của provider `milvus`.

`remote.py` (AsyncMilvusClient, async thuần) và `inprocess.py` (MilvusClient + Milvus
Lite, sync + to_thread) chia sẻ: map record→row, ráp kết quả search. Toàn bộ payload
nằm trong MỘT field động `payload` (JSON) nên không cần khai báo schema cứng; collection
tạo bằng quick-setup (id + vector COSINE). KHÔNG enforce access (search.md §6).

base KHÔNG import pymilvus — phần thuần dữ liệu; client do từng file deployment nạp.
"""

from __future__ import annotations

from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.provider import VectorStoreProvider
from core_engine.vectorstore.types import VectorRecord

PK = "id"
VECTOR = "vector"
PAYLOAD = "payload"


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
