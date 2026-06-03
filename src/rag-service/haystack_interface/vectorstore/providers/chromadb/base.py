"""Phần dùng chung cho hai deployment của provider `chromadb`.

`remote.py` (AsyncHttpClient, async thuần) và `inprocess.py` (Ephemeral/Persistent,
sync + to_thread) chia sẻ: encode/decode metadata (Chroma chỉ nhận scalar nên list
như allowed_departments phải JSON-encode), dựng tham số add/upsert, và ráp kết quả
query + POST-FILTER `can_access` (Chroma where không lọc được list → lọc sau).
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from app.domain.repositories.vector_repository import SearchResult, UserContext

from haystack_interface.access import can_access
from haystack_interface.vectorstore.config import VectorStoreConfig
from haystack_interface.vectorstore.provider import VectorStoreProvider
from haystack_interface.vectorstore.types import VectorRecord

# Chroma metadata chỉ nhận scalar; field nào là list/dict thì JSON-encode.
_JSON_FIELDS = ("allowed_departments", "allowed_user_ids")
# Lấy dư rồi post-filter access → tránh hụt kết quả sau khi lọc quyền.
OVERFETCH = 5
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
        out = dict(meta or {})
        for field in _JSON_FIELDS:
            raw = out.get(field)
            if isinstance(raw, str):
                try:
                    out[field] = json.loads(raw)
                except json.JSONDecodeError:
                    out[field] = []
        return out

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

    def _assemble(self, res: dict, user_context: UserContext, top_k: int) -> list[SearchResult]:
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        ids = (res.get("ids") or [[]])[0]
        out: list[SearchResult] = []
        for i, raw_meta in enumerate(metas):
            meta = self._decode_meta(raw_meta or {})
            if not can_access(meta, user_context):
                continue
            distance = dists[i] if i < len(dists) else None
            document = docs[i] if i < len(docs) else ""
            out.append(self._to_result(ids[i], meta, document, distance))
            if len(out) >= top_k:
                break
        return out

    @staticmethod
    def _to_result(chunk_id: str, m: dict, document: str, distance) -> SearchResult:
        # cosine distance -> similarity (1 - distance).
        score = (1.0 - float(distance)) if distance is not None else 0.0
        return SearchResult(
            chunk_id=m.get("chunk_id", chunk_id),
            parent_id=m.get("parent_id", ""),
            document_id=m.get("document_id", ""),
            document_name=m.get("document_name", ""),
            file_type=m.get("file_type", ""),
            page_number=int(m.get("page_number", 0)),
            section_title=m.get("section_title", ""),
            child_text=m.get("child_text", document or ""),
            parent_text=m.get("parent_text", ""),
            score=score,
            rerank_score=float(m.get("rerank_score", 0.0)),
        )
