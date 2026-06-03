"""haystack_interface — core working RAG của rag-service, dựng trên Haystack.

Kiến trúc module (severable, mỗi module một nhiệm vụ — MOSA / hexagonal):

    ai/          AI gateway — điểm vào DUY NHẤT cho mọi outbound AI call
                 (embed · caption · rerank); OpenAI SDK trước, swap provider 1 chỗ.
    embedding/   port EmbeddingService qua provider
    chunking/    section split (đơn vị nghĩa, không token-chunk)
    caption/     ý-nghĩa-nén section qua provider
    rerank/      Reranker (LLM qua gateway / lexical fallback)
    vectorstore/ port VectorRepository (provider-first: qdrant·chromadb·milvus)
    access/      classification filter (policy)
    engine.py    orchestrator (ingest + search), chỉ phụ thuộc port
    factory.py   composition root — wire backend theo env (offline | OpenAI)

Mọi capability lấy chung một AI provider singleton → ingest & query cùng
provider/model/dimension (search.md §2). Đổi provider/backend = đổi wiring ở
factory + ai/, KHÔNG sửa engine/use-case.

    from haystack_interface import build_engine, IngestInput
    from app.domain.repositories.vector_repository import UserContext

    engine = build_engine()                  # auto theo env (offline nếu không có key)
    await engine.ingest(IngestInput(document_id="d1", document_name="Doc",
                                    file_type="md", markdown="# Title\nNội dung..."))
    hits = await engine.search("câu hỏi", UserContext("u1", "user", "eng"))
"""

from haystack_interface.config import HaystackSettings, load_settings
from haystack_interface.engine import HaystackRagEngine, IngestInput
from haystack_interface.factory import build_engine, build_engine_probe

# AI gateway (điểm vào AI duy nhất).
from haystack_interface.ai import (
    AIProvider,
    AISettings,
    get_ai_provider,
    set_ai_provider,
    reset_ai_provider,
    OpenAIProvider,
    OfflineProvider,
)

# Port adapters + capability (cho composition tuỳ biến / test).
from haystack_interface.embedding import ProviderEmbeddingService
from haystack_interface.vectorstore import (
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
from haystack_interface.caption import Captioner, ProviderCaptioner
from haystack_interface.rerank import Reranker, LLMReranker, LexicalRerankerService

__all__ = [
    # composition
    "build_engine",
    "build_engine_probe",
    "HaystackRagEngine",
    "IngestInput",
    "HaystackSettings",
    "load_settings",
    # AI gateway
    "AIProvider",
    "AISettings",
    "get_ai_provider",
    "set_ai_provider",
    "reset_ai_provider",
    "OpenAIProvider",
    "OfflineProvider",
    # ports / capabilities
    "ProviderEmbeddingService",
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
    "Reranker",
    "LLMReranker",
    "LexicalRerankerService",
]
