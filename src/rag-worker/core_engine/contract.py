from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

PAYLOAD_SCHEMA_VERSION = 1

# Phiên bản thuật toán SPARSE (BM25). Bump khi đổi cách encode sparse (token->index,
# value, modifier IDF...) -> index_id đổi -> collection MỚI -> auto-migrate kích hoạt
# y như đổi embed model (forward-only, collection cũ giữ để rollback). sparse_version
# chỉ áp khi hybrid bật; =0 (dense-only) GIỮ NGUYÊN tên + fingerprint cũ (no-op).
#   v1 = TF chuẩn-hoá-theo-tổng, KHÔNG IDF (BM25-lite cũ).
#   v2 = BM25 thật: TF bão hoà (k1/b/avgdl) phía document + Modifier.IDF của Qdrant.
# PHẢI khớp mcp-service/app/core/contract.py::SPARSE_ENCODING_VERSION.
# GOTCHA (e2e 2026-06-23): hybrid bật ở producer (rag-worker) NHƯNG quên ở consumer (mcp)
# -> 2 bên sinh index_id lệch (__s2 vs no-suffix) -> mcp_contract_verify_failed -> 0 sources.
# => VECTOR_HYBRID phải set GIỐNG NHAU cho CẢ rag-worker LẪN mcp ở MỌI môi trường.
SPARSE_ENCODING_VERSION = 2

EMBED_MODELS: dict[str, dict[str, object]] = {
    "text-embedding-3-small": {"native": 1536, "allowed": "256..1536"},
    "text-embedding-3-large": {"native": 3072, "allowed": "256..3072"},
    "bge-m3": {"native": 1024, "allowed": {1024}},
    # qwen3-embedding-4b qua OpenRouter (DeepInfra): native 2560, MRL 32..2560.
    "qwen/qwen3-embedding-4b": {"native": 2560, "allowed": "32..2560"},
    "offline": {"native": 256, "allowed": {256}},
}

MODEL_TAGS = {
    "text-embedding-3-small": "te3s",
    "text-embedding-3-large": "te3l",
    "bge-m3": "bgem3",
    "qwen/qwen3-embedding-4b": "qwen3emb4b",   # collection: {base}__qwen3emb4b__d2560
    "offline": "offline",
}


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


def index_id(collection: str, model: str, dimension: int, *, sparse_version: int = 0) -> str:
    base = collection.strip()
    if not base:
        raise ValueError("VECTOR_COLLECTION must not be empty")
    # sparse_version>0 (hybrid BM25) -> hậu tố __s{ver} => collection MỚI khi bump.
    # =0 (dense-only / schema cũ) -> KHÔNG hậu tố => giữ nguyên tên prod hiện tại.
    suffix = f"__s{int(sparse_version)}" if sparse_version and int(sparse_version) > 0 else ""
    return f"{base}__{model_tag(model)}__d{int(dimension)}{suffix}"


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
    sparse_version: int = 0,
) -> str:
    resolved = resolve_dimension(embed_model, dimension)
    payload: dict[str, object] = {
        "provider": provider.strip().lower(),
        "collection": collection.strip(),
        "embed_model": _normalize_model(embed_model),
        "dimension": int(resolved),
        "schema_version": int(schema_version),
    }
    # Chỉ thêm key khi >0 -> fingerprint dense-only (sparse_version=0) GIỮ NGUYÊN
    # bit-by-bit như trước => KHÔNG vỡ stamp collection prod hiện tại.
    if sparse_version and int(sparse_version) > 0:
        payload["sparse_version"] = int(sparse_version)
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def resolve_vectorstore_contract(
    *,
    provider: str,
    collection: str,
    embed_model: str,
    dimension: int | None,
    schema_version: int = PAYLOAD_SCHEMA_VERSION,
    sparse_version: int = 0,
) -> ResolvedVectorstoreContract:
    resolved_dim = resolve_dimension(embed_model, dimension)
    normalized_model = _normalize_model(embed_model)
    return ResolvedVectorstoreContract(
        provider=provider.strip().lower(),
        collection=collection.strip(),
        embed_model=normalized_model,
        dimension=resolved_dim,
        schema_version=int(schema_version),
        index_id=index_id(
            collection, normalized_model, resolved_dim, sparse_version=sparse_version
        ),
        fingerprint=vectorstore_fingerprint(
            provider=provider,
            collection=collection,
            embed_model=normalized_model,
            dimension=resolved_dim,
            schema_version=schema_version,
            sparse_version=sparse_version,
        ),
    )


def build_contract_stamp(contract: ResolvedVectorstoreContract) -> dict[str, object]:
    return {
        "kind": "__contract__",
        "index_id": contract.index_id,
        "fingerprint": contract.fingerprint,
        "provider": contract.provider,
        "collection": contract.collection,
        "embed_model": contract.embed_model,
        "dimension": contract.dimension,
        "schema_version": contract.schema_version,
    }
