from __future__ import annotations

import pytest

from core_engine import OfflineProvider, build_engine_from_config
from core_engine.config_schema import PipelineConfig
from core_engine.engine import IngestInput
from core_engine.mapping import WireContext, register, resolve
from core_engine.ocr import ProviderImageTextExtractor


def test_register_and_resolve_override() -> None:
    provider = OfflineProvider(128)
    ctx = WireContext(
        provider=provider,
        dim=128,
        ocr_extractor=ProviderImageTextExtractor(provider),
    )
    register("test_component", "demo", lambda params, ctx: ("first", params), override=True)

    assert (
        resolve(
            "test_component",
            type("_Stage", (), {"impl": "demo", "params": {"x": 1}})(),
            ctx,
        )
        == ("first", {"x": 1})
    )

    register("test_component", "demo", lambda params, ctx: ("second", params), override=True)

    assert (
        resolve(
            "test_component",
            type("_Stage", (), {"impl": "demo", "params": {"x": 2}})(),
            ctx,
        )
        == ("second", {"x": 2})
    )


def test_build_engine_from_config_wires_builtin_components() -> None:
    cfg = PipelineConfig.model_validate(
        {
            "common": {"ai_mode": "offline"},
            "embedder": {"model": "text-embedding-3-small", "dimension": 256},
            "captioner": {"impl": "none", "model": "gpt-4o-mini", "params": {}},
            "parser": {"impl": "local", "params": {"max_workers": 2}},
            "chunker": {
                "impl": "heading_sections",
                "params": {
                    "parent_max_words": 220,
                    "child_max_words": 90,
                    "child_overlap_words": 15,
                },
            },
            "vector_store": {
                "impl": "qdrant",
                "params": {"collection": "rag_chatbot", "url": "", "api_key": ""},
            },
        }
    )

    engine = build_engine_from_config(cfg, provider=OfflineProvider(256))

    assert engine.captioner is None
    assert engine.settings.embed_dimension == 256


@pytest.mark.asyncio
async def test_engine_from_config_string_params_can_ingest() -> None:
    # Params số đến từ ${VAR} interpolation dưới dạng string. Engine phải ingest được,
    # không vỡ do các giá trị size/max_workers còn ở dạng chuỗi.
    cfg = PipelineConfig.model_validate(
        {
            "common": {"ai_mode": "offline"},
            "embedder": {"model": "m", "dimension": 256},
            "captioner": {"impl": "provider", "model": "m", "params": {"max_chars": "6000"}},
            "parser": {"impl": "local", "params": {"max_workers": "2"}},
            "chunker": {
                "impl": "heading_sections",
                "params": {
                    "parent_max_words": "220",
                    "child_max_words": "90",
                    "child_overlap_words": "15",
                },
            },
            "vector_store": {
                "impl": "qdrant",
                "params": {"collection": "rag_chatbot", "url": "", "api_key": ""},
            },
        }
    )

    engine = build_engine_from_config(cfg, provider=OfflineProvider(256))
    n = await engine.ingest(
        IngestInput(
            document_id="d1",
            document_name="Doc",
            file_type="md",
            markdown="# Title\nhello world content for retrieval",
        )
    )
    assert n > 0
    assert await engine.vectors.list_chunk_ids_by_document("d1")
