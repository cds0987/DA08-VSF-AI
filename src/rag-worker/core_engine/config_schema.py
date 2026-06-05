from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CommonConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ai_mode: Literal["offline", "openai", "auto"] = "auto"
    timeout: float = 60.0
    max_retries: int = 5


class EmbedderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "text-embedding-3-small"
    base_url: str = ""
    api_key: str = ""
    dimension: int = 1024

    @model_validator(mode="after")
    def validate_embedder(self) -> "EmbedderConfig":
        if self.dimension <= 0:
            raise ValueError("EMBED_DIMENSION must be > 0")
        if not self.model.strip():
            raise ValueError("AI config for embed must include a model")
        return self


class ComponentWithParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    impl: str
    params: dict[str, Any] = Field(default_factory=dict)


class CaptionerConfig(ComponentWithParams):
    model: str = "gpt-4o-mini"
    base_url: str = ""
    api_key: str = ""

    @model_validator(mode="after")
    def validate_captioner(self) -> "CaptionerConfig":
        if self.impl != "none" and not self.model.strip():
            raise ValueError("AI config for caption must include a model")
        return self


class RerankerConfig(ComponentWithParams):
    model: str = "gpt-4o-mini"
    base_url: str = ""
    api_key: str = ""

    @model_validator(mode="after")
    def validate_reranker(self) -> "RerankerConfig":
        if self.impl == "llm" and not self.model.strip():
            raise ValueError("AI config for rerank must include a model")
        return self


class ParserOcrConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = ""
    base_url: str = ""
    api_key: str = ""

    @model_validator(mode="after")
    def validate_ocr(self) -> "ParserOcrConfig":
        if self.model and not self.model.strip():
            raise ValueError("AI config for ocr must include a model")
        return self


class ParserConfig(ComponentWithParams):
    ocr: ParserOcrConfig | None = None

    @model_validator(mode="after")
    def validate_parser(self) -> "ParserConfig":
        if int(self.params.get("max_workers", 2)) <= 0:
            raise ValueError("PARSER_MAX_WORKERS must be > 0")
        return self


class ChunkerConfig(ComponentWithParams):
    @model_validator(mode="after")
    def validate_chunker(self) -> "ChunkerConfig":
        parent_max_words = int(self.params.get("parent_max_words", 220))
        child_max_words = int(self.params.get("child_max_words", 90))
        child_overlap_words = int(self.params.get("child_overlap_words", 15))
        if parent_max_words <= 0:
            raise ValueError("SECTION_MAX_WORDS must be > 0")
        if child_max_words <= 0:
            raise ValueError("CHILD_MAX_WORDS must be > 0")
        if child_overlap_words < 0:
            raise ValueError("CHILD_OVERLAP_WORDS must be >= 0")
        if child_overlap_words >= child_max_words:
            raise ValueError("CHILD_OVERLAP_WORDS must be < CHILD_MAX_WORDS")
        return self


class VectorStoreConfigModel(ComponentWithParams):
    @model_validator(mode="after")
    def validate_vector_store(self) -> "VectorStoreConfigModel":
        collection = str(self.params.get("collection", ""))
        if not collection.strip():
            raise ValueError("VECTOR_COLLECTION must not be empty")
        return self


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_k_candidates: int = 20
    rerank_top_k: int = 3
    rerank_threshold: float = 0.7

    @model_validator(mode="after")
    def validate_retrieval(self) -> "RetrievalConfig":
        if self.top_k_candidates <= 0:
            raise ValueError("SEARCH_TOP_K must be > 0")
        if self.rerank_top_k <= 0:
            raise ValueError("RERANK_TOP_K must be > 0")
        if self.top_k_candidates < self.rerank_top_k:
            raise ValueError("SEARCH_TOP_K must be >= RERANK_TOP_K")
        if not 0.0 <= self.rerank_threshold <= 1.0:
            raise ValueError("RERANK_THRESHOLD must be between 0 and 1")
        return self


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    common: CommonConfig = Field(default_factory=CommonConfig)
    embedder: EmbedderConfig = Field(default_factory=EmbedderConfig)
    captioner: CaptionerConfig = Field(
        default_factory=lambda: CaptionerConfig(impl="provider")
    )
    reranker: RerankerConfig = Field(
        default_factory=lambda: RerankerConfig(impl="llm")
    )
    parser: ParserConfig = Field(default_factory=lambda: ParserConfig(impl="local"))
    chunker: ChunkerConfig = Field(
        default_factory=lambda: ChunkerConfig(
            impl="heading_sections",
            params={
                "parent_max_words": 220,
                "child_max_words": 90,
                "child_overlap_words": 15,
            },
        )
    )
    vector_store: VectorStoreConfigModel = Field(
        default_factory=lambda: VectorStoreConfigModel(
            impl="qdrant",
            params={"collection": "rag_chatbot", "url": "", "api_key": ""},
        )
    )
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
