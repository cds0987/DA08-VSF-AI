"""Phần dùng chung cho hai deployment của provider `chromadb`.

`remote.py` (AsyncHttpClient, async thuần) và `inprocess.py` (Ephemeral/Persistent,
sync + to_thread) chia sẻ: encode/decode metadata (Chroma chỉ nhận scalar nên list/dict
phải JSON-encode), dựng tham số add/upsert, và ráp kết quả query. KHÔNG enforce access
control — trả raw unit + lineage (search.md §6).
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.provider import VectorStoreProvider
from core_engine.vectorstore.types import VectorRecord

COLLECTION_METADATA = {"hnsw:space": "cosine"}


class ChromaBase(VectorStoreProvider):
    def __init__(self, config: VectorStoreConfig | None = None):
        super().__init__(config or VectorStoreConfig(provider="chromadb"))

    @property
    def collection_name(self) -> str:
        return self.config.index_id()

    # --- mapping payload <-> chroma metadata (scalar-only) ------------------- #
    @staticmethod
    def _encode_meta(payload) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, (list, dict)):
                meta[key] = json.dumps(value, ensure_ascii=False)
            elif value is not None:
                meta[key] = value
        return meta

    @staticmethod
    def _decode_meta(meta: dict[str, Any]) -> dict[str, Any]:
        decoded: dict[str, Any] = {}
        for key, value in (meta or {}).items():
            if isinstance(value, str) and value[:1] in {"[", "{"}:
                try:
                    decoded[key] = json.loads(value)
                    continue
                except json.JSONDecodeError:
                    pass
            decoded[key] = value
        return decoded

    def _add_args(self, records: Sequence[VectorRecord]) -> dict:
        ids, embeddings, metadatas, documents = [], [], [], []
        for record in records:
            if len(record.vector) != self.config.dimension:
                raise ValueError(
                    f"Sai dimension: vector={len(record.vector)} != index={self.config.dimension}. "
                    "Doi dimension la migration (ingestion.md §8)."
                )
            ids.append(record.chunk_id)
            embeddings.append(list(record.vector))
            metadatas.append(self._encode_meta(record.payload))
            documents.append(record.payload.get("bm25_text") or record.payload.get("child_text", ""))
        return {"ids": ids, "embeddings": embeddings, "metadatas": metadatas, "documents": documents}

    @staticmethod
    def _dup_id(existing: dict) -> str | None:
        ids = (existing or {}).get("ids") or []
        return sorted(ids)[0] if ids else None

    @staticmethod
    def _ids(existing: dict) -> list[str]:
        ids = (existing or {}).get("ids") or []
        if ids and isinstance(ids[0], list):
            return list(ids[0])
        return list(ids)
