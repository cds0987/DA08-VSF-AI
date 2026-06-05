from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from core_engine.contract import (
    ResolvedVectorstoreContract,
    build_contract_stamp,
    meta_collection_name,
)
from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.providers.qdrant.base import point_id


class VectorstoreContractError(RuntimeError):
    """Contract vector store lệch giữa producer (ingest) và consumer (search).

    Fail-closed: consumer (mcp-service) raise lỗi này lúc startup là CHẶN phục vụ
    search — thà crash còn hơn trả kết quả rác do embed sai không gian. Xem
    docs/search-split-vectorstore-contract.md §7.3.
    """


async def write_contract_stamp(
    vector_config: VectorStoreConfig,
    *,
    written_by: str,
) -> None:
    if vector_config.provider.lower() != "qdrant":
        return

    from qdrant_client import AsyncQdrantClient, QdrantClient, models

    contract = vector_config.contract()
    payload = build_contract_stamp(contract)
    payload["written_by"] = written_by
    payload["written_at"] = datetime.now(UTC).isoformat()
    collection_name = meta_collection_name(vector_config.collection)
    point = models.PointStruct(
        id=point_id(f"__contract__::{contract.index_id}"),
        vector=[1.0],
        payload=payload,
    )
    vectors_config = models.VectorParams(size=1, distance=models.Distance.COSINE)

    if vector_config.deployment == "remote":
        client = AsyncQdrantClient(
            url=vector_config.url or None,
            api_key=vector_config.api_key or None,
            **dict(vector_config.options),
        )
        if not await client.collection_exists(collection_name):
            await client.create_collection(
                collection_name=collection_name,
                vectors_config=vectors_config,
            )
        await client.upsert(collection_name=collection_name, points=[point])
        await client.close()
        return

    options = dict(vector_config.options)
    if "location" not in options and "path" not in options:
        options["location"] = ":memory:"
    client = QdrantClient(**options)

    def _write() -> None:
        if not client.collection_exists(collection_name):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=vectors_config,
            )
        client.upsert(collection_name=collection_name, points=[point])
        close = getattr(client, "close", None)
        if callable(close):
            close()

    await asyncio.to_thread(_write)


# --- Consumer side (mcp-service): verify dấu niêm, fail-closed ---------------


def check_stamp(stamp: dict | None, contract: ResolvedVectorstoreContract) -> None:
    """So dấu niêm đọc từ Qdrant với contract của consumer. Lệch/thiếu -> raise.

    Hàm THUẦN (không I/O) -> unit-test được không cần Qdrant.
    """
    if stamp is None:
        raise VectorstoreContractError(
            f"Thiếu dấu niêm contract cho index={contract.index_id} "
            f"(collection {meta_collection_name(contract.collection)} chưa có stamp). "
            "Producer (rag-worker) chưa ingest/đóng dấu, hoặc consumer trỏ sai collection."
        )
    actual = str(stamp.get("fingerprint", ""))
    if actual != contract.fingerprint:
        raise VectorstoreContractError(
            f"Fingerprint lệch cho index={contract.index_id}: "
            f"consumer={contract.fingerprint} vs stamp={actual or '(trống)'}. "
            f"stamp(model={stamp.get('embed_model')} dim={stamp.get('dimension')} "
            f"schema={stamp.get('schema_version')} by={stamp.get('written_by')}). "
            "Đổi embed_model/dimension/payload schema là MIGRATION (re-ingest)."
        )


def _vector_size(info: object) -> int | None:
    params = getattr(getattr(info, "config", None), "params", None)
    vectors = getattr(params, "vectors", None)
    if vectors is None:
        return None
    if hasattr(vectors, "size"):
        return int(vectors.size)
    if isinstance(vectors, dict) and len(vectors) == 1:
        only = next(iter(vectors.values()))
        size = getattr(only, "size", None)
        return int(size) if size is not None else None
    return None


def _assert_contract(
    contract: ResolvedVectorstoreContract,
    *,
    data_exists: bool,
    vector_size: int | None,
    stamp: dict | None,
    expect_data_collection: bool,
) -> None:
    if expect_data_collection:
        if not data_exists:
            raise VectorstoreContractError(
                f"Collection dữ liệu {contract.index_id} chưa tồn tại trên Qdrant. "
                "Producer (rag-worker) chưa ingest, hoặc consumer dùng model/dim khác."
            )
        if vector_size is not None and vector_size != contract.dimension:
            raise VectorstoreContractError(
                f"Vector size lệch cho {contract.index_id}: store={vector_size} "
                f"vs contract={contract.dimension}. Đổi dimension là migration."
            )
    check_stamp(stamp, contract)


async def verify_contract_or_raise(
    vector_config: VectorStoreConfig,
    *,
    expect_data_collection: bool = True,
) -> ResolvedVectorstoreContract:
    """Consumer verify contract với Qdrant thật. Lệch/thiếu -> VectorstoreContractError.

    Gọi lúc startup của mcp-service (fail-closed). Trả contract đã resolve nếu OK.
    Provider không phải qdrant: bỏ qua (chưa hỗ trợ) -> trả contract, không chặn.
    """
    contract = vector_config.contract()
    if vector_config.provider.lower() != "qdrant":
        return contract

    from qdrant_client import AsyncQdrantClient, QdrantClient

    data_collection = contract.index_id
    meta_collection = meta_collection_name(vector_config.collection)
    stamp_id = point_id(f"__contract__::{contract.index_id}")

    if vector_config.deployment == "remote":
        client = AsyncQdrantClient(
            url=vector_config.url or None,
            api_key=vector_config.api_key or None,
            **dict(vector_config.options),
        )
        try:
            data_exists = await client.collection_exists(data_collection)
            vector_size = (
                _vector_size(await client.get_collection(data_collection))
                if data_exists
                else None
            )
            stamp = None
            if await client.collection_exists(meta_collection):
                records = await client.retrieve(
                    collection_name=meta_collection, ids=[stamp_id], with_payload=True
                )
                if records:
                    stamp = records[0].payload
        finally:
            await client.close()
        _assert_contract(
            contract,
            data_exists=data_exists,
            vector_size=vector_size,
            stamp=stamp,
            expect_data_collection=expect_data_collection,
        )
        return contract

    options = dict(vector_config.options)
    if "location" not in options and "path" not in options:
        options["location"] = ":memory:"
    client = QdrantClient(**options)

    def _read() -> tuple[bool, int | None, dict | None]:
        try:
            exists = client.collection_exists(data_collection)
            size = _vector_size(client.get_collection(data_collection)) if exists else None
            payload = None
            if client.collection_exists(meta_collection):
                records = client.retrieve(
                    collection_name=meta_collection, ids=[stamp_id], with_payload=True
                )
                if records:
                    payload = records[0].payload
            return exists, size, payload
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    data_exists, vector_size, stamp = await asyncio.to_thread(_read)
    _assert_contract(
        contract,
        data_exists=data_exists,
        vector_size=vector_size,
        stamp=stamp,
        expect_data_collection=expect_data_collection,
    )
    return contract
