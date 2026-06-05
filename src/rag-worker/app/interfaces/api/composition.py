from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.domain.repositories.parser import Parser
from app.infrastructure.external.local_parser import LocalFileParser
from app.infrastructure.external.s3_parser import S3SourceParser
from core_engine.ocr import ProviderImageTextExtractor
from core_engine.registry import Registry

ParserFactory = Callable[[Mapping[str, Any], ProviderImageTextExtractor], Parser]

# Cùng primitive với core_engine registry (chunker/vectorstore/...). Parser sống ở
# tầng app vì layering (Parser là port của app.domain), nhưng dùng CHUNG cơ chế
# đăng ký + entry-point discovery → một pattern cho toàn pipeline.
_PARSER_REGISTRY: Registry[ParserFactory] = Registry(
    "parser", entry_point_group="rag_worker.parser"
)


def register_parser(
    name: str,
    factory: ParserFactory,
    *,
    override: bool = False,
) -> None:
    _PARSER_REGISTRY.register(name, factory, override=override)


def resolve_parser(
    name: str,
    *,
    params: Mapping[str, Any] | None = None,
    image_text_extractor: ProviderImageTextExtractor,
) -> Parser:
    factory = _PARSER_REGISTRY.get(name)
    return factory(dict(params or {}), image_text_extractor)


register_parser(
    "local",
    lambda params, image_text_extractor: LocalFileParser(
        max_workers=int(params.get("max_workers", 2)),
        image_text_extractor=image_text_extractor,
    ),
)

# `s3`: BE chỉ gửi source_uri=s3://... ; parser tự tải an toàn (HEAD size-guard +
# stream-to-disk + cap + semaphore) rồi giao bản local cho LocalFileParser parse.
register_parser(
    "s3",
    lambda params, image_text_extractor: S3SourceParser(
        LocalFileParser(
            max_workers=int(params.get("max_workers", 2)),
            image_text_extractor=image_text_extractor,
        ),
    ),
)
