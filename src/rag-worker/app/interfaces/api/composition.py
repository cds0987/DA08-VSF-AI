from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.domain.repositories.parser import Parser
from app.infrastructure.external.local_parser import LocalFileParser
from core_engine.ocr import ProviderImageTextExtractor

ParserFactory = Callable[[Mapping[str, Any], ProviderImageTextExtractor], Parser]

_PARSER_REGISTRY: dict[str, ParserFactory] = {}


def register_parser(
    name: str,
    factory: ParserFactory,
    *,
    override: bool = False,
) -> None:
    key = name.lower()
    if key in _PARSER_REGISTRY and not override:
        raise ValueError(f"Parser {key!r} da dang ky")
    _PARSER_REGISTRY[key] = factory


def resolve_parser(
    name: str,
    *,
    params: Mapping[str, Any] | None = None,
    image_text_extractor: ProviderImageTextExtractor,
) -> Parser:
    key = name.lower()
    factory = _PARSER_REGISTRY.get(key)
    if factory is None:
        raise ValueError(f"Parser {key!r} chua dang ky")
    return factory(dict(params or {}), image_text_extractor)


register_parser(
    "local",
    lambda params, image_text_extractor: LocalFileParser(
        max_workers=int(params.get("max_workers", 2)),
        image_text_extractor=image_text_extractor,
    ),
)
