"""Qdrant deployment `remote` — service riêng (có url), ASYNC THUẦN.

Dùng khi `config.url` có giá trị (Qdrant Cloud hoặc self-hosted server). Client
`AsyncQdrantClient` là async-native nên KHÔNG cần to_thread.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Sequence

logger = logging.getLogger(__name__)

from core_engine.vectorstore.providers.qdrant.base import (
    QdrantBase,
    is_qdrant_collection_missing_error,
    point_id,
)

from qdrant_client import AsyncQdrantClient, models

from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.store import VectorStore
from core_engine.vectorstore.types import SearchHit, VectorRecord


class QdrantRemoteProvider(QdrantBase):
    def __init__(self, config: VectorStoreConfig | None = None):
        super().__init__(config)
        self._client = AsyncQdrantClient(**self.config.remote_client_kwargs())
        self._ready = False
        self._lock = asyncio.Lock()
        self._upsert_batch = max(1, int(os.getenv("UPSERT_BATCH_SIZE", "256")))
        # Cache chế độ collection (hybrid vs dense) -> chọn query tương thích ngược.
        self._mode: str | None = None

    async def _ensure(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            if not await self._client.collection_exists(self._collection):
                await self._client.create_collection(
                    collection_name=self._collection,
                    **self._collection_create_kwargs(),
                )
                # Filter theo document_id (dedup scroll + delete + scoped search) yêu cầu
                # payload index keyword; Qdrant Cloud bật "indexing required for filtering"
                # nên thiếu index -> 400. Tạo ngay lúc tạo collection (idempotent).
                await self._client.create_payload_index(
                    collection_name=self._collection,
                    field_name="document_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            self._ready = True

    async def _retry_on_missing_collection(
        self,
        op: Callable[[], Awaitable[object]],
    ) -> object:
        try:
            return await op()
        except Exception as exc:
            if not is_qdrant_collection_missing_error(exc):
                raise
            self._ready = False
            await self._ensure()
            return await op()

    async def insert_many(self, records: Sequence[VectorRecord]) -> None:
        record_list = list(records)
        if not record_list:
            return

        async def op() -> None:
            await self._ensure()
            points = await self._client.retrieve(
                collection_name=self._collection,
                ids=[point_id(r.chunk_id) for r in record_list],
                with_payload=True,
                with_vectors=False,
            )
            existing = self._existing_from_points(points)
            if existing:
                raise ValueError(
                    f"Chunk id da ton tai, insert khong duoc overwrite: {sorted(existing)[0]}"
                )
            await self._client.upsert(
                collection_name=self._collection,
                points=[self._point(r) for r in record_list],
                wait=True,  # chờ index xong -> point SEARCHABLE ngay (hết race query-ngay-sau-ingest)
            )

        await self._retry_on_missing_collection(op)

    async def upsert_many(self, records: Sequence[VectorRecord]) -> None:
        record_list = list(records)
        if not record_list:
            return
        points = [self._point(r) for r in record_list]

        async def op() -> None:
            await self._ensure()
            for index in range(0, len(points), self._upsert_batch):
                try:
                    await self._client.upsert(
                        collection_name=self._collection,
                        points=points[index : index + self._upsert_batch],
                        wait=True,  # chờ index xong -> point SEARCHABLE ngay (hết race ingest->query)
                    )
                except Exception as exc:  # DIAG upsert 400 "Not existing vector name": log body THẬT
                    p0 = points[index]
                    try:
                        vkeys = (
                            {k: type(v).__name__ for k, v in p0.vector.items()}
                            if isinstance(p0.vector, dict)
                            else f"LIST(unnamed,len={len(p0.vector)})"
                        )
                        body = p0.model_dump_json()
                        body = body[:280] + ("...sparse..." + body[body.find('"sparse"'):body.find('"sparse"') + 120] if '"sparse"' in body else "")
                    except Exception as e2:
                        vkeys, body = f"vkeys-err:{e2}", "??"
                    try:
                        info = await self._client.get_collection(self._collection)
                        live_vec = str(info.config.params.vectors)[:200]
                        live_sparse = str(info.config.params.sparse_vectors)[:200]
                    except Exception as e3:
                        live_vec = live_sparse = f"info-err:{e3}"
                    logger.error(
                        "DIAG qdrant_upsert_fail coll=%s hybrid=%s prefer_grpc=%s err=%s\n"
                        "  point0.vector=%s\n  point0.body=%s\n  LIVE collection.vectors=%s\n  LIVE sparse_vectors=%s",
                        self._collection, self.config.hybrid,
                        getattr(self._client, "_prefer_grpc", "?"), exc,
                        vkeys, body, live_vec, live_sparse,
                    )
                    raise

        await self._retry_on_missing_collection(op)

    async def list_chunk_ids_by_document(self, document_id: str) -> list[str]:
        async def op() -> list[str]:
            await self._ensure()
            chunk_ids: set[str] = set()
            offset = None
            while True:
                points, offset = await self._client.scroll(
                    collection_name=self._collection,
                    scroll_filter=self._document_filter(document_id),
                    with_payload=True,
                    with_vectors=False,
                    limit=1000,
                    offset=offset,
                )
                chunk_ids.update(self._existing_from_points(points))
                if offset is None:
                    break
            return sorted(chunk_ids)

        return await self._retry_on_missing_collection(op)

    async def delete_many(self, chunk_ids: Sequence[str]) -> None:
        ids = list(chunk_ids)
        if not ids:
            return

        async def op() -> None:
            await self._ensure()
            await self._client.delete(
                collection_name=self._collection,
                points_selector=self._ids_selector(ids),
            )

        await self._retry_on_missing_collection(op)

    async def delete_by_document(self, document_id: str) -> None:
        async def op() -> None:
            await self._ensure()
            await self._client.delete(
                collection_name=self._collection,
                points_selector=self._delete_by_document_selector(document_id),
            )

        await self._retry_on_missing_collection(op)

    async def _resolve_mode(self) -> str:
        if self._mode is None:
            try:
                info = await self._client.get_collection(self._collection)
                self._mode = self._collection_mode(info)
            except Exception:  # noqa: BLE001 — không lấy được info -> an toàn: dense trần
                self._mode = "dense"
        return self._mode

    async def search(
        self,
        *,
        query_vector: Sequence[float],
        query_text: str,
        top_k: int,
        document_ids: Sequence[str] | None,
    ) -> list[SearchHit]:
        doc_filter = self._access_filter(document_ids)

        async def op() -> list[SearchHit]:
            await self._ensure()
            mode = await self._resolve_mode()
            if mode == "hybrid":
                kwargs = self._hybrid_query_kwargs(query_vector, query_text, top_k, doc_filter)
            else:
                kwargs = self._dense_query_kwargs(query_vector, top_k, doc_filter)
            res = await self._client.query_points(**kwargs)
            return [self._to_search_hit(p.payload, p.score) for p in res.points]

        return await self._retry_on_missing_collection(op)


class QdrantRemoteRepository(VectorStore):
    def __init__(self, config: VectorStoreConfig | None = None):
        provider = QdrantRemoteProvider(config)
        super().__init__(provider, provider.config)
