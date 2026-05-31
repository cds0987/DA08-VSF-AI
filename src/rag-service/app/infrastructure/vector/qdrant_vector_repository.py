# TODO: RAG Engineer
# Implements VectorRepository using Qdrant client
# hybrid_search: kết hợp dense vector (BGE-M3) + sparse BM25 → RRF fusion
# Classification filter logic theo docs/contracts.md → VectorRepository.hybrid_search docstring
from app.domain.repositories.vector_repository import VectorRepository
