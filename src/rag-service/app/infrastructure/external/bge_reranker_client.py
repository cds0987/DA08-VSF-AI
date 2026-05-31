# TODO: RAG Engineer
# BGE-Reranker-v2-m3 client — gọi self-hosted reranker service
# Input: query + List[SearchResult] (Top-20)
# Output: List[SearchResult] sorted by rerank_score, threshold=0.7
# URL từ: BGE_RERANKER_URL env var
