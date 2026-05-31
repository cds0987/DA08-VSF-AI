# TODO: RAG Engineer
# 5-step retrieval pipeline:
# 1. embed(query_text) → query vector (BGE-M3)
# 2. hybrid_search(vector, query_text, user_context, top_k=20) → List[SearchResult] (RRF)
# 3. rerank(query_text, results) → Top-3 (BGE-Reranker-v2-m3, threshold=0.7)
# 4. Filter results với score < threshold
# 5. Return List[SearchResult] (tối đa 3)
