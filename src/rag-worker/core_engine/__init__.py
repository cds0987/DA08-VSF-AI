"""core_engine — core working RAG của rag-service, dựng trên Haystack.

Kiến trúc module (severable, mỗi module một nhiệm vụ — MOSA / hexagonal):

    ai/          AI gateway — điểm vào DUY NHẤT cho mọi outbound AI call
                 (embed · caption · rerank); OpenAI SDK trước, swap provider 1 chỗ.
    embedding/   port EmbeddingService qua provider
    chunking/    section split (đơn vị nghĩa, không token-chunk)
    caption/     ý-nghĩa-nén section qua provider
    rerank/      Reranker (LLM qua gateway / lexical fallback)
    vectorstore/ port VectorRepository (provider-first: qdrant·chromadb·milvus)
    engine.py    orchestrator (ingest + search), chỉ phụ thuộc port
    factory.py   composition root — wire backend theo env (offline | OpenAI)

Mọi capability lấy chung một AI provider singleton → ingest & query cùng
provider/model/dimension (search.md §2). Đổi provider/backend = đổi wiring ở
factory + ai/, KHÔNG sửa engine/use-case.

    from core_engine import build_engine, IngestInput

    engine = build_engine()                  # auto theo env (offline nếu không có key)
    await engine.ingest(IngestInput(document_id="d1", document_name="Doc",
                                    file_type="md", markdown="# Title\nNội dung..."))
    hits = await engine.search("câu hỏi")    # trả raw unit + lineage; access ở caller
"""

from core_engine.config import HaystackSettings, load_settings
from core_engine.contract import (
    EMBED_MODELS,
    PAYLOAD_SCHEMA_VERSION,
    ResolvedVectorstoreContract,
    index_id,
    model_tag,
    resolve_dimension,
    resolve_vectorstore_contract,
    vectorstore_fingerprint,
)
from core_engine.engine import HaystackRagEngine, IngestInput
from core_engine.factory import build_engine, build_engine_probe
from core_engine.mapping import build_engine_from_config, register
from core_engine.registry import Registry

# AI gateway (điểm vào AI duy nhất).
from core_engine.ai import (
    AIProvider,
    AISettings,
    get_ai_provider,
    set_ai_provider,
    reset_ai_provider,
    OpenAIProvider,
    OfflineProvider,
)

# Port adapters + capability (cho composition tuỳ biến / test).
from core_engine.embedding import ProviderEmbeddingService
from core_engine.types import (
    EmbeddingService,
    SearchLineage,
    SearchResult,
    VectorRepository,
)
from core_engine.vectorstore import (
    VectorRecord,
    VectorStoreConfig,
    VectorStore,
    VectorStoreProvider,
    build_vector_store,
    build_vector_repository,
    register_backend,
    register_provider,
    available_backends,
    available_providers,
)
from core_engine.caption import Captioner, ProviderCaptioner
from core_engine.chunking import Chunker, SectionChunker
from core_engine.rerank import (
    Reranker,
    LLMReranker,
    LexicalRerankerService,
    NoopRerankerService,
)

__all__ = [
    # composition
    "build_engine",
    "build_engine_probe",
    "build_engine_from_config",
    "register",
    "Registry",
    "HaystackRagEngine",
    "IngestInput",
    "HaystackSettings",
    "load_settings",
    "EMBED_MODELS",
    "PAYLOAD_SCHEMA_VERSION",
    "ResolvedVectorstoreContract",
    "resolve_dimension",
    "model_tag",
    "index_id",
    "resolve_vectorstore_contract",
    "vectorstore_fingerprint",
    # AI gateway
    "AIProvider",
    "AISettings",
    "get_ai_provider",
    "set_ai_provider",
    "reset_ai_provider",
    "OpenAIProvider",
    "OfflineProvider",
    # ports / capabilities
    "EmbeddingService",
    "ProviderEmbeddingService",
    "SearchLineage",
    "SearchResult",
    "VectorRepository",
    "VectorRecord",
    "VectorStore",
    "VectorStoreProvider",
    "VectorStoreConfig",
    "build_vector_store",
    "build_vector_repository",
    "register_backend",
    "register_provider",
    "available_backends",
    "available_providers",
    "Captioner",
    "ProviderCaptioner",
    "Chunker",
    "SectionChunker",
    "Reranker",
    "LLMReranker",
    "LexicalRerankerService",
    "NoopRerankerService",
]
