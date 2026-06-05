from __future__ import annotations

import pytest

from core_engine.contract import (
    EMBED_MODELS,
    PAYLOAD_SCHEMA_VERSION,
    index_id,
    model_tag,
    resolve_dimension,
    resolve_vectorstore_contract,
    vectorstore_fingerprint,
)


def test_embed_model_registry_exposes_expected_defaults() -> None:
    assert EMBED_MODELS["text-embedding-3-small"]["native"] == 1536
    assert EMBED_MODELS["offline"]["native"] == 256


@pytest.mark.parametrize(
    ("model", "override", "expected"),
    [
        ("text-embedding-3-small", None, 1536),
        ("text-embedding-3-small", 256, 256),
        ("text-embedding-3-large", 3072, 3072),
        ("bge-m3", 1024, 1024),
        ("offline", None, 256),
    ],
)
def test_resolve_dimension_accepts_valid_values(
    model: str,
    override: int | None,
    expected: int,
) -> None:
    assert resolve_dimension(model, override) == expected


@pytest.mark.parametrize(
    ("model", "override"),
    [
        ("text-embedding-3-small", 128),
        ("bge-m3", 512),
        ("offline", 1024),
    ],
)
def test_resolve_dimension_rejects_invalid_overrides(
    model: str,
    override: int,
) -> None:
    with pytest.raises(ValueError):
        resolve_dimension(model, override)


def test_resolve_dimension_requires_override_for_unknown_models() -> None:
    with pytest.raises(ValueError, match="EMBED_MODELS"):
        resolve_dimension("custom-model")

    assert resolve_dimension("custom-model", 2048) == 2048


def test_model_tag_and_index_id_are_stable() -> None:
    assert model_tag("text-embedding-3-small") == "te3s"
    assert index_id("rag_chatbot", "text-embedding-3-small", 1536) == "rag_chatbot__te3s__d1536"
    assert index_id("rag_chatbot", "my custom/model", 2048) == "rag_chatbot__my-custom-model__d2048"


def test_vectorstore_fingerprint_changes_when_any_field_changes() -> None:
    base = vectorstore_fingerprint(
        provider="qdrant",
        collection="rag_chatbot",
        embed_model="text-embedding-3-small",
        dimension=1536,
        schema_version=PAYLOAD_SCHEMA_VERSION,
    )
    changed_model = vectorstore_fingerprint(
        provider="qdrant",
        collection="rag_chatbot",
        embed_model="text-embedding-3-large",
        dimension=3072,
        schema_version=PAYLOAD_SCHEMA_VERSION,
    )
    changed_schema = vectorstore_fingerprint(
        provider="qdrant",
        collection="rag_chatbot",
        embed_model="text-embedding-3-small",
        dimension=1536,
        schema_version=PAYLOAD_SCHEMA_VERSION + 1,
    )

    assert len(base) == 16
    assert base != changed_model
    assert base != changed_schema


def test_resolve_vectorstore_contract_returns_index_and_fingerprint() -> None:
    contract = resolve_vectorstore_contract(
        provider="qdrant",
        collection="rag_chatbot",
        embed_model="text-embedding-3-small",
        dimension=None,
    )

    assert contract.dimension == 1536
    assert contract.index_id == "rag_chatbot__te3s__d1536"
    assert contract.fingerprint
