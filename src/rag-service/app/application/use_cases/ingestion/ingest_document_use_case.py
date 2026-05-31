# TODO: RAG Engineer
# 7-step ingestion pipeline:
# 1. Download file từ S3
# 2. Detect file type → route đến parser phù hợp
# 3. PDF scan → Azure Document Intelligence OCR | PDF text layer → PyMuPDF
# 4. Split text → parent chunks (512-1024 tokens) + child chunks (128-256 tokens)
# 5. embed_batch(child_texts) → vectors (1024 dims, BGE-M3)
# 6. upsert(chunk_id, vector, payload) vào Qdrant — payload chứa parent_text + metadata
# 7. update_status(document_id, COMPLETED, chunk_count)
