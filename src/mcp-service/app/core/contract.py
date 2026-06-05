"""Vector store contract — BẢN RIÊNG của mcp-service (KHÔNG import rag-worker).

mcp-service là service độc lập (xem memory mcp-service-independent). Logic ở đây
PHẢI cho ra giá trị Y HỆT rag-worker/core_engine/contract.py: cùng fingerprint,
cùng index_id, cùng model_tag, cùng PAYLOAD_SCHEMA_VERSION. Drift giữa 2 bản được
bắt bởi: (a) CI fingerprint parity, (b) dấu niêm Qdrant (mcp tự tính fingerprint
bằng code NÀY rồi so với stamp producer ghi).

Nếu sửa file này, PHẢI sửa đối xứng rag-worker/core_engine/contract.py.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

PAYLOAD_SCHEMA_VERSION = 1

EMBED_MODELS: dict[str, dict[str, object]] = {
    "text-embedding-3-small": {"native": 1536, "allowed": "256..1536"},
    "text-embedding-3-large": {"native": 3072, "allowed": "256..3072"},
    "bge-m3": {"native": 1024, "allowed": {1024}},
    "offline": {"native": 256, "allowed": {256}},
}

MODEL_TAGS = {
    "text-embedding-3-small": "te3s",
    "text-embedding-3-large": "te3l",
    "bge-m3": "bgem3",
    "offline": "offline",
}


class VectorstoreContractError(RuntimeError):
    """Contract vector store lệch giữa producer (rag-worker) và consumer (mcp).

    Fail-closed: mcp raise lỗi này lúc startup = CHẶN phục vụ search.
    """


@dataclass(frozen=True)
class ResolvedVectorstoreContract:
    provider: str
    collection: str
    embed_model: str
    dimension: int
    schema_version: int
    index_id: str
    fingerprint: str


def _normalize_model(model: str) -> str:
    normalized = model.strip().lower()
    if not normalized:
        raise ValueError("EMBED_MODEL must not be empty")
    return normalized


def _is_allowed(value: int, allowed: object) -> bool:
    if isinstance(allowed, set):
        return value in allowed
    if isinstance(allowed, str):
        match = re.fullmatch(r"(\d+)\.\.(\d+)", allowed)
        if match:
            lower, upper = (int(part) for part in match.groups())
            return lower <= value <= upper
    return False


def resolve_dimension(model: str, override: int | None = None) -> int:
    normalized = _normalize_model(model)
    spec = EMBED_MODELS.get(normalized)
    if spec is None:
        if override is None:
            raise ValueError(
                f"model {model!r} chua co trong EMBED_MODELS, phai set EMBED_DIMENSION ro rang"
            )
        if int(override) <= 0:
            raise ValueError("EMBED_DIMENSION must be > 0")
        return int(override)
    if override is None:
        return int(spec["native"])
    resolved = int(override)
    if resolved <= 0:
        raise ValueError("EMBED_DIMENSION must be > 0")
    if not _is_allowed(resolved, spec["allowed"]):
        raise ValueError(
            f"model {model!r} khong cho dimension={resolved} (allowed={spec['allowed']})"
        )
    return resolved


def _slug(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "model"


def model_tag(model: str) -> str:
    normalized = _normalize_model(model)
    return MODEL_TAGS.get(normalized, _slug(normalized))


def index_id(collection: str, model: str, dimension: int) -> str:
    base = collection.strip()
    if not base:
        raise ValueError("VECTOR_COLLECTION must not be empty")
    return f"{base}__{model_tag(model)}__d{int(dimension)}"


def meta_collection_name(collection: str) -> str:
    base = collection.strip()
    if not base:
        raise ValueError("VECTOR_COLLECTION must not be empty")
    return f"{base}__meta"


def vectorstore_fingerprint(
    *,
    provider: str,
    collection: str,
    embed_model: str,
    dimension: int | None,
    schema_version: int,
) -> str:
    resolved = resolve_dimension(embed_model, dimension)
    payload = json.dumps(
        {
            "provider": provider.strip().lower(),
            "collection": collection.strip(),
            "embed_model": _normalize_model(embed_model),
            "dimension": int(resolved),
            "schema_version": int(schema_version),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def resolve_vectorstore_contract(
    *,
    provider: str,
    collection: str,
    embed_model: str,
    dimension: int | None,
    schema_version: int = PAYLOAD_SCHEMA_VERSION,
) -> ResolvedVectorstoreContract:
    resolved_dim = resolve_dimension(embed_model, dimension)
    normalized_model = _normalize_model(embed_model)
    return ResolvedVectorstoreContract(
        provider=provider.strip().lower(),
        collection=collection.strip(),
        embed_model=normalized_model,
        dimension=resolved_dim,
        schema_version=int(schema_version),
        index_id=index_id(collection, normalized_model, resolved_dim),
        fingerprint=vectorstore_fingerprint(
            provider=provider,
            collection=collection,
            embed_model=normalized_model,
            dimension=resolved_dim,
            schema_version=schema_version,
        ),
    )


def check_stamp(stamp: dict | None, contract: ResolvedVectorstoreContract) -> None:
    """So dấu niêm đọc từ Qdrant với contract của mcp. Lệch/thiếu -> raise.

    Hàm THUẦN (không I/O) -> unit-test được không cần Qdrant.
    """
    if stamp is None:
        raise VectorstoreContractError(
            f"Thiếu dấu niêm contract cho index={contract.index_id} "
            f"(collection {meta_collection_name(contract.collection)} chưa có stamp). "
            "Producer (rag-worker) chưa ingest/đóng dấu, hoặc mcp trỏ sai collection."
        )
    actual = str(stamp.get("fingerprint", ""))
    if actual != contract.fingerprint:
        raise VectorstoreContractError(
            f"Fingerprint lệch cho index={contract.index_id}: "
            f"mcp={contract.fingerprint} vs stamp={actual or '(trống)'}. "
            f"stamp(model={stamp.get('embed_model')} dim={stamp.get('dimension')} "
            f"schema={stamp.get('schema_version')} by={stamp.get('written_by')}). "
            "Đổi embed_model/dimension/payload schema là MIGRATION (re-ingest)."
        )
