from __future__ import annotations

from typing import Any, Literal

from core_engine.contract import resolve_dimension

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    dimension: int | None = None

    @field_validator("dimension", mode="before")
    @classmethod
    def blank_dimension_means_auto(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    @model_validator(mode="after")
    def validate_embedder(self) -> "EmbedderConfig":
        if not self.model.strip():
            raise ValueError("AI config for embed must include a model")
        resolve_dimension(self.model, self.dimension)
        return self


class VectorstoreContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    collection: str
    embed_model: str

    @model_validator(mode="after")
    def validate_contract(self) -> "VectorstoreContractConfig":
        if not self.provider.strip():
            raise ValueError("vectorstore_contract.provider must not be empty")
        if not self.collection.strip():
            raise ValueError("vectorstore_contract.collection must not be empty")
        if not self.embed_model.strip():
            raise ValueError("vectorstore_contract.embed_model must not be empty")
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


class ReaderConfig(ComponentWithParams):
    """Engine giải mã MỘT định dạng file (vd pdf -> pymupdf|pypdf).

    `impl` tra `_READER_REGISTRY` trong local_parser; `params` truyền vào factory
    reader. Section optional — thiếu thì local_parser dùng bản đồ suffix->impl mặc
    định (backward-compatible).
    """


class ParserConfig(ComponentWithParams):
    ocr: ParserOcrConfig | None = None
    readers: dict[str, ReaderConfig] = Field(default_factory=dict)

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


class LangfuseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    public_key: str = ""
    secret_key: str = ""
    host: str = "http://langfuse-web:3000"
    sample_rate: float = 0.0
    trace_on_error: bool = True

    @model_validator(mode="after")
    def validate_langfuse(self) -> "LangfuseConfig":
        if self.sample_rate < 0 or self.sample_rate > 1:
            raise ValueError("LANGFUSE_SAMPLE_RATE must be between 0 and 1")
        return self


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    common: CommonConfig = Field(default_factory=CommonConfig)
    embedder: EmbedderConfig = Field(default_factory=EmbedderConfig)
    captioner: CaptionerConfig = Field(
        default_factory=lambda: CaptionerConfig(impl="provider")
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
    vectorstore_contract: VectorstoreContractConfig | None = None
    langfuse: LangfuseConfig = Field(default_factory=LangfuseConfig)
