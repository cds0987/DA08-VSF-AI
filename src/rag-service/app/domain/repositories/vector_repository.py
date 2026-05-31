from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class UserContext:
    user_id: str
    user_role: str          # "admin" | "user"
    user_department: str    # dùng để filter secret docs trong Qdrant


@dataclass
class SearchResult:
    chunk_id: str
    parent_id: str
    document_id: str
    document_name: str
    file_type: str
    page_number: int
    section_title: str
    child_text: str
    parent_text: str        # đưa vào LLM prompt
    score: float            # hybrid search score (RRF)
    rerank_score: float     # score sau BGE-Reranker-v2-m3, None nếu chưa rerank


class VectorRepository(ABC):

    @abstractmethod
    async def upsert(self, chunk_id: str, vector: List[float], payload: dict) -> None:
        """Lưu vector + metadata vào Qdrant."""

    @abstractmethod
    async def hybrid_search(
        self,
        vector: List[float],
        query_text: str,
        user_context: UserContext,
        top_k: int = 20
    ) -> List[SearchResult]:
        """Hybrid search (vector + BM25 RRF) với classification filter theo user_context.
        top_k=20 là candidates trước rerank — RAG Engineer rerank xuống Top-3 sau đó.
        Filter logic:
          public      → không filter
          internal    → user.is_active
          secret      → allowed_departments contains user_context.user_department
          top_secret  → allowed_user_ids contains user_context.user_id
        """

    @abstractmethod
    async def delete_by_document(self, document_id: str) -> None:
        """Xóa toàn bộ vectors của một document."""
