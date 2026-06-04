# Hướng dẫn học Vector Database từ nền tảng đến production

Tài liệu này tổng hợp lộ trình học và triển khai Vector Database theo hướng thực dụng: hiểu bản chất, biết cách chọn công nghệ, nắm các lỗi thường gặp và có thể bắt đầu xây dựng RAG hoặc semantic search trong môi trường production.

## 1. Nền tảng lý thuyết

### 1.1. Vector Database là gì?

Vector Database là hệ cơ sở dữ liệu được tối ưu cho việc lưu trữ, lập chỉ mục và truy vấn embedding vector. Embedding là các mảng số biểu diễn ý nghĩa ngữ nghĩa của văn bản, hình ảnh, âm thanh, video hoặc một thực thể bất kỳ.

Ví dụ:

```text
"Cách reset mật khẩu?" -> [0.12, -0.33, 0.91, ...]
"Quên password thì làm sao?" -> [0.10, -0.29, 0.88, ...]
```

Hai câu có từ ngữ khác nhau nhưng gần nghĩa nên vector của chúng thường nằm gần nhau trong không gian vector.

### 1.2. Vì sao cần Vector Database?

| Nhu cầu | SQL | Elasticsearch/BM25 | Vector DB |
| --- | --- | --- | --- |
| Tìm exact match | Tốt | Tốt | Không phải mục tiêu chính |
| Tìm theo keyword | Kém | Rất tốt | Trung bình nếu không dùng hybrid |
| Tìm theo ngữ nghĩa | Kém | Giới hạn | Rất tốt |
| RAG chatbot | Khó | Dùng được nhưng thiếu semantic | Rất phù hợp |
| Image similarity | Không phù hợp | Không phù hợp | Rất phù hợp |
| Metadata filtering | Rất tốt | Tốt | Tùy từng hệ |
| ANN search quy mô lớn | Không native | Có kNN | Là mục tiêu cốt lõi |

### 1.3. Phân biệt ba nhóm thường bị nhầm lẫn

| Loại | Ví dụ | Bản chất | Khi nên dùng |
| --- | --- | --- | --- |
| Vector Database | Pinecone, Weaviate, Qdrant, Milvus, Chroma, LanceDB | Có storage, index, API, metadata, replication, filtering | Production RAG, semantic search |
| Vector Index Library | FAISS, Annoy, ScaNN, USearch | Chỉ là thư viện index/search, chưa phải DB hoàn chỉnh | Local search, nghiên cứu, embedded app |
| Database + Vector Extension | PostgreSQL + pgvector, Elasticsearch kNN, MongoDB Atlas Vector Search | DB truyền thống có thêm vector search | Khi muốn tận dụng hạ tầng sẵn có |

### 1.4. Embedding là gì?

Embedding là vector số do mô hình sinh ra để biểu diễn ý nghĩa của dữ liệu đầu vào.

| Loại embedding | Input | Use case |
| --- | --- | --- |
| Text embedding | Câu, đoạn, chunk tài liệu | RAG, semantic search |
| Image embedding | Ảnh | Image search, duplicate detection |
| Multimodal embedding | Text + image + audio/video | Tìm kiếm đa phương thức |
| Sparse embedding | Term-weight style | Hybrid search, keyword-aware retrieval |
| Dense embedding | Vector float dày đặc | Similarity search |

`Dimension` là số chiều của vector. Ví dụ, một embedding model có thể trả về vector `384` hoặc `1536` chiều.

Dimension lớn hơn không đồng nghĩa với tốt hơn. Nó ảnh hưởng trực tiếp tới dung lượng lưu trữ và chi phí index:

```text
storage xấp xỉ số_vector × số_chiều × 4 byte
```

Ví dụ, `10M vectors × 1536 dim × float32` đã tiêu tốn khoảng `61.4 GB` dữ liệu thô, chưa tính index, metadata và replication.

### 1.5. Similarity search cơ bản

#### Distance metrics

| Metric | Ý nghĩa trực quan | Khi dùng | Lưu ý |
| --- | --- | --- | --- |
| Cosine Similarity | So góc giữa hai vector | Text embedding phổ biến | Thường cần normalize |
| Euclidean / L2 | Khoảng cách hình học | Image, clustering | Nhạy với magnitude |
| Dot Product / Inner Product | Tích vô hướng | Model được train theo dot product | Magnitude ảnh hưởng kết quả |
| Manhattan / L1 | Tổng chênh lệch từng chiều | Một số bài toán đặc thù | Ít dùng trong RAG |

Quy tắc thực tế: dùng metric mà embedding model khuyến nghị, không tự đổi metric chỉ vì một lựa chọn nào đó đang phổ biến hơn.

#### Exact search và ANN

| Loại | Cách làm | Ưu điểm | Nhược điểm |
| --- | --- | --- | --- |
| Exact / brute force | So query với toàn bộ vector | Recall 100% | Chậm khi dữ liệu lớn |
| ANN | Tìm gần đúng qua index | Nhanh hơn rất nhiều | Recall < 100% |

Production luôn phải cân bằng giữa ba yếu tố:

```text
Recall tăng  -> Latency tăng, Memory tăng
Latency giảm -> Recall có thể giảm
Memory giảm  -> Recall hoặc latency thường xấu đi
```

### 1.6. Các thuật toán index quan trọng

| Index | Ý tưởng | Ưu điểm | Nhược điểm | Khi dùng |
| --- | --- | --- | --- | --- |
| Flat | Quét toàn bộ vector | Chính xác nhất | Chậm, tốn CPU | Dataset nhỏ, benchmark ground truth |
| IVF | Chia vector thành cụm/bucket | Nhanh, tiết kiệm hơn Flat | Cần tune `nlist`, `nprobe` | Dataset lớn |
| HNSW | Đồ thị nhiều tầng | Recall/latency rất tốt | Tốn RAM | Mặc định tốt cho nhiều workload |
| PQ | Nén vector thành mã ngắn | Tiết kiệm RAM/disk | Giảm recall | Dữ liệu rất lớn |
| DiskANN | Giữ phần lớn index trên SSD | Scale lớn, tiết kiệm RAM | Phụ thuộc SSD | Hàng trăm triệu đến hàng tỷ vector |
| IVF-PQ | Kết hợp shortlist và nén | Scale tốt | Dễ giảm recall nếu tune kém | Hệ thống bị giới hạn bộ nhớ |

### 1.7. Khái niệm cốt lõi

| Khái niệm | Giải thích | Ví dụ |
| --- | --- | --- |
| Collection | Nhóm vector cùng schema | `support_articles` |
| Index | Cấu trúc tăng tốc search | HNSW cho collection |
| Namespace | Phân vùng logic | Mỗi khách hàng một namespace |
| Dimension | Số chiều vector | `1536` |
| Metadata / Payload | Dữ liệu đi kèm vector | `tenant_id`, `doc_id`, `lang` |
| Metadata filter | Lọc theo metadata | Chỉ search tài liệu của tenant A |
| Pre-filter | Lọc trước khi vector search | Tốt khi filter có độ chọn lọc cao |
| Post-filter | Search trước, lọc sau | Dễ làm mất kết quả đúng |
| Hybrid search | Kết hợp vector và keyword/BM25 | Vừa semantic vừa lexical |
| Multi-tenancy | Cô lập dữ liệu nhiều tenant | SaaS RAG |
| Sharding | Chia dữ liệu qua nhiều node | Scale lớn |
| Replication | Nhân bản dữ liệu | Tăng HA và read throughput |
| Consistency | Độ nhất quán dữ liệu mới | Strong hoặc eventual |

## 2. So sánh các lựa chọn phổ biến

### 2.1. Bảng so sánh nhanh

| Option | Loại | Điểm mạnh | Điểm yếu | Phù hợp nhất |
| --- | --- | --- | --- | --- |
| Pinecone | Managed vector DB | Ít vận hành, scale nhanh | Lock-in, chi phí theo usage | Enterprise RAG |
| Weaviate | OSS + Cloud | Hybrid search tốt, schema rõ | Self-host cần kinh nghiệm | Knowledge base, hybrid RAG |
| Qdrant | OSS + Cloud | Filtering mạnh, payload index tốt | Vẫn cần hiểu sâu khi scale | SaaS RAG, metadata-heavy |
| Milvus / Zilliz | OSS distributed + managed | Scale lớn, nhiều loại index | Self-host phức tạp | Hệ rất lớn |
| Chroma | OSS + Cloud | Dễ dùng, hợp prototype | Production lớn cần cân nhắc | MVP, local RAG |
| LanceDB | Embedded / Cloud | Hợp multimodal, dữ liệu lakehouse | Ecosystem nhỏ hơn | Image, multimodal |
| pgvector | PostgreSQL extension | Tận dụng Postgres, ACID, JOIN tốt | ANN và scale có giới hạn | App đã dùng Postgres |
| Elasticsearch / OpenSearch kNN | Search engine + vector | Keyword search mạnh | Vector không phải gốc lõi từ đầu | Search product, catalog |
| Redis Vector Search | In-memory | Latency thấp | Chi phí RAM cao | Realtime matching |
| MongoDB Atlas Vector Search | Document DB + vector | Gắn chặt với document JSON | Phụ thuộc Atlas | App đã dùng MongoDB |
| FAISS | Library | Cực mạnh cho local/research | Không có DB ops | Custom engine, benchmark |

### 2.2. Decision matrix

| Nếu bạn cần... | Nên chọn |
| --- | --- |
| Prototype nhanh, embedded, không cần server | Chroma hoặc LanceDB |
| RAG chatbot dưới 1M tài liệu | Chroma, Qdrant, pgvector |
| Production 10M-100M vectors, cần SLA | Pinecone, Qdrant Cloud, Zilliz Cloud, Weaviate Cloud |
| Đã có PostgreSQL, không muốn thêm hạ tầng | pgvector |
| Hybrid search vector + BM25 | Weaviate, Elasticsearch/OpenSearch, MongoDB Atlas |
| Multi-tenant SaaS | Qdrant, Pinecone namespace, Weaviate |
| On-prem hoặc air-gapped | Milvus, Qdrant, Weaviate, pgvector |
| Budget thấp | pgvector, Qdrant self-host, Chroma |

### 2.3. Trade-off thực tế

#### Managed cloud và self-hosted

| Managed cloud | Self-hosted |
| --- | --- |
| Vào production nhanh | Có thể rẻ hơn nếu đội vận hành tốt |
| Có SLA, support | Kiểm soát infra và dữ liệu tốt hơn |
| Dễ scale | Phải tự xử lý backup, monitoring, upgrade |
| Có nguy cơ lock-in | Phải tự xử lý incident |

#### Dedicated vector DB và vector extension

| Dedicated Vector DB | Vector extension |
| --- | --- |
| Tối ưu ANN/filter/scale | Tận dụng DB sẵn có |
| Nhiều tính năng vector-native | Kiến trúc đơn giản hơn |
| Cần thêm một hệ mới | Có thể đụng giới hạn khi scale lớn |

## 3. Workflow RAG đầy đủ

```text
Documents
  ↓
Chunking
  ↓
Embedding
  ↓
Upsert vào Vector DB
  ↓
User Query
  ↓
Query Embedding
  ↓
Similarity Search Top-K
  ↓
Metadata Filter
  ↓
Reranking
  ↓
LLM Prompt
  ↓
Answer
```

Pipeline tối thiểu:

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

docs = [
    {"id": "1", "text": "Vector database dùng cho semantic search.", "tenant_id": "acme"},
    {"id": "2", "text": "PostgreSQL có extension pgvector.", "tenant_id": "acme"},
]

texts = [d["text"] for d in docs]
vectors = model.encode(texts, normalize_embeddings=True).tolist()
```

## 4. Ví dụ thực hành

### 4.1. Chroma

```bash
pip install chromadb sentence-transformers
```

```python
import chromadb
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_or_create_collection(name="docs")

docs = [
    {"id": "doc1", "text": "Vector DB lưu embedding để semantic search.", "tenant_id": "acme"},
    {"id": "doc2", "text": "FastAPI hỗ trợ REST API và WebSocket.", "tenant_id": "acme"},
]

embeddings = model.encode(
    [d["text"] for d in docs],
    normalize_embeddings=True,
).tolist()

collection.upsert(
    ids=[d["id"] for d in docs],
    documents=[d["text"] for d in docs],
    embeddings=embeddings,
    metadatas=[{"tenant_id": d["tenant_id"]} for d in docs],
)

query = "semantic search hoạt động như thế nào?"
query_vec = model.encode([query], normalize_embeddings=True).tolist()[0]

results = collection.query(
    query_embeddings=[query_vec],
    n_results=3,
    where={"tenant_id": "acme"},
)

print(results)
```

### 4.2. Qdrant

```bash
pip install qdrant-client sentence-transformers
```

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
client = QdrantClient(path="./qdrant_local")

collection_name = "docs"

client.recreate_collection(
    collection_name=collection_name,
    vectors_config=VectorParams(size=384, distance=Distance.COSINE),
)

docs = [
    {"id": 1, "text": "Qdrant hỗ trợ payload filtering mạnh.", "tenant_id": "acme"},
    {"id": 2, "text": "Vector search tìm theo ý nghĩa.", "tenant_id": "acme"},
]

vectors = model.encode(
    [d["text"] for d in docs],
    normalize_embeddings=True,
).tolist()

client.upsert(
    collection_name=collection_name,
    points=[
        PointStruct(
            id=d["id"],
            vector=vectors[i],
            payload={"text": d["text"], "tenant_id": d["tenant_id"]},
        )
        for i, d in enumerate(docs)
    ],
)

query_vec = model.encode(
    ["tìm kiếm ngữ nghĩa là gì?"],
    normalize_embeddings=True,
).tolist()[0]

hits = client.search(
    collection_name=collection_name,
    query_vector=query_vec,
    query_filter=Filter(
        must=[
            FieldCondition(
                key="tenant_id",
                match=MatchValue(value="acme"),
            )
        ]
    ),
    limit=3,
)

for hit in hits:
    print(hit.score, hit.payload["text"])
```

### 4.3. pgvector

```bash
pip install psycopg[binary] pgvector sentence-transformers
```

SQL khởi tạo:

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(384)
);

CREATE INDEX documents_embedding_hnsw_idx
ON documents
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX documents_tenant_id_idx
ON documents (tenant_id);
```

Mã Python:

```python
import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

conn = psycopg.connect("postgresql://postgres:postgres@localhost:5432/app")
register_vector(conn)

docs = [
    ("acme", "pgvector lưu embedding trực tiếp trong PostgreSQL."),
    ("acme", "HNSW index hỗ trợ approximate nearest neighbor search."),
]

with conn.cursor() as cur:
    for tenant_id, content in docs:
        embedding = model.encode(content, normalize_embeddings=True).tolist()
        cur.execute(
            """
            INSERT INTO documents (tenant_id, content, embedding)
            VALUES (%s, %s, %s)
            """,
            (tenant_id, content, embedding),
        )
    conn.commit()

query_embedding = model.encode(
    "Postgres tìm kiếm vector như thế nào?",
    normalize_embeddings=True,
).tolist()

with conn.cursor() as cur:
    cur.execute(
        """
        SELECT id, content, 1 - (embedding <=> %s) AS similarity
        FROM documents
        WHERE tenant_id = %s
        ORDER BY embedding <=> %s
        LIMIT 5
        """,
        (query_embedding, "acme", query_embedding),
    )

    for row in cur.fetchall():
        print(row)
```

## 5. Các operation quan trọng

| Operation | Ý nghĩa |
| --- | --- |
| Create collection/index | Tạo nơi lưu vector và cấu trúc truy vấn |
| Insert / upsert | Thêm mới hoặc ghi đè vector |
| Similarity search | Tìm `top-k` hàng xóm gần nhất |
| Filtered search | Search trong tập con theo metadata |
| Hybrid search | Kết hợp dense vector và keyword/sparse |
| Delete / update | Quản lý vòng đời dữ liệu |
| Batch insert | Ingest số lượng lớn |
| Stats / metrics | Theo dõi count, latency, index size |

Nên có abstraction trong ứng dụng:

```python
class VectorStore:
    def upsert(self, ids, texts, embeddings, metadatas):
        raise NotImplementedError

    def search(self, query_embedding, top_k, filters=None):
        raise NotImplementedError

    def delete(self, ids):
        raise NotImplementedError
```

Không nên gắn chặt business logic vào SDK của một vendor cụ thể nếu bạn có khả năng phải thay đổi backend sau này.

## 6. Các lỗi kinh điển

### 6.1. Dùng hai embedding model khác nhau

```python
# Sai
index_embedding = openai_embed_v1(doc)
query_embedding = local_bge_embed(query)
```

Lỗi này không làm hệ thống crash nhưng kết quả retrieval thường sai vì vector nằm ở hai không gian khác nhau.

### 6.2. Sai dimension

```python
# Collection cấu hình 1536 nhưng model trả về 384
VectorParams(size=1536, distance=Distance.COSINE)
```

Điều này thường làm insert hoặc query thất bại.

### 6.3. Không normalize khi cần

```python
# Sai
vectors = model.encode(texts).tolist()

# Đúng
vectors = model.encode(texts, normalize_embeddings=True).tolist()
```

### 6.4. Chunk quá lớn hoặc quá nhỏ

Điểm bắt đầu hợp lý thường là `300-800 tokens`, overlap `50-150`. Chunk quá lớn làm context bị loãng, chunk quá nhỏ làm mất ngữ cảnh.

### 6.5. Quên tenant filter

```python
# Sai
results = vector_db.search(query_vec, top_k=5)

# Đúng
results = vector_db.search(
    query_vec,
    top_k=5,
    filters={"tenant_id": current_tenant_id},
)
```

Đây là lỗi rất nguy hiểm trong hệ multi-tenant vì có thể gây lộ dữ liệu.

### 6.6. Sai logic filter AND/OR

Filter phức tạp phải viết theo đúng DSL của từng hệ. Không nên giả định rằng list value luôn được hiểu là `OR`.

### 6.7. Dùng exact search cho dữ liệu rất lớn

```python
# Sai
index_type = "FLAT"

# Hợp lý hơn
index_type = "HNSW"
```

### 6.8. Không đo recall

Chỉ theo dõi latency là chưa đủ. Cần có evaluation set để đo:

```text
recall@5
MRR
nDCG
p95/p99 latency
empty result rate
tenant leakage test
```

### 6.9. Duplicate vector

Nếu mỗi lần upsert cùng một nội dung lại sinh ID mới, `top-k` rất dễ lặp lại nhiều đoạn giống nhau, làm context nghèo đi.

### 6.10. Embedding drift

Khi đổi embedding model mà không reindex, chất lượng retrieval giảm mạnh. Nên lưu metadata về model và version embedding để kiểm soát vòng đời dữ liệu.

### 6.11. Post-filter gây mất kết quả

```python
# Sai
hits = search(query_vec, top_k=5)
hits = [h for h in hits if h["tenant_id"] == "acme"]
```

Nên lọc ngay trong engine nếu hệ hỗ trợ.

### 6.12. Không tạo payload/scalar index

Nếu bạn filter thường xuyên theo `tenant_id`, `lang`, `category` mà không tạo index cho các field này, hiệu năng filtered search sẽ giảm rõ rệt.

## 7. Lộ trình học đề xuất

### Bước 1. Hiểu embedding bằng trực quan hóa

Encode vài trăm câu tiếng Việt, dùng PCA, t-SNE hoặc UMAP để quan sát các cụm nghĩa.

### Bước 2. FAISS local semantic search

Thực hành trên khoảng `10K FAQ`, so sánh Flat, HNSW, IVF và đo `recall@k`, `latency`.

### Bước 3. Chroma embedded RAG

Xây chatbot đọc tài liệu local hoặc PDF để học chunking, metadata, persistent storage và basic RAG.

### Bước 4. Qdrant hoặc Milvus theo phong cách production

Tập trung vào payload index, batch upsert, collection config, backup và monitoring.

### Bước 5. pgvector trong ứng dụng PostgreSQL

Học cách kết hợp vector search với dữ liệu quan hệ, `JOIN` và `EXPLAIN ANALYZE`.

### Bước 6. Hybrid search

Kết hợp BM25, dense vector, sparse vector, reranking và score fusion.

### Bước 7. Multi-tenant RAG

Xây SaaS chatbot nhiều workspace để luyện tenant isolation và security testing.

### Bước 8. Benchmark

So sánh Chroma, Qdrant, pgvector hoặc các hệ khác trên cùng dataset và cùng tiêu chí đo.

### Bước 9. Production

Học backup/restore, rolling migration, index rebuild, model versioning, observability, cost control và incident playbook.

## 8. Mười nguyên tắc vàng cho production

1. Luôn version hóa embedding model và lưu rõ `embedding_model`, `dimension`, `metric`, `created_at`.
2. Không search multi-tenant nếu thiếu `tenant filter` hoặc cơ chế namespace tương đương.
3. Benchmark trên dữ liệu thật, không chỉ trên dữ liệu synthetic.
4. Theo dõi recall song song với latency.
5. Thiết kế reindex pipeline ngay từ đầu.
6. Dùng batch ingest thay vì insert từng vector.
7. Tạo metadata hoặc payload index cho các field hay filter.
8. Không chọn DB chỉ vì benchmark công khai đẹp; phải khớp workload thực tế.
9. Có abstraction layer để giảm phụ thuộc sâu vào SDK của vendor.
10. Tính tổng chi phí sở hữu, bao gồm RAM, disk, read/write, replica, backup, rebuild và thời gian vận hành.

## 9. Gợi ý chọn nhanh

| Bối cảnh | Gợi ý |
| --- | --- |
| Học từ đầu | FAISS -> Chroma -> Qdrant -> pgvector |
| RAG MVP | Chroma hoặc Qdrant |
| App đang dùng Postgres | pgvector |
| SaaS nhiều tenant, filter nặng | Qdrant hoặc Pinecone |
| Scale rất lớn, self-host | Milvus |
| Enterprise managed | Pinecone, Weaviate Cloud, Zilliz Cloud |
| Search có keyword mạnh | Weaviate, Elasticsearch/OpenSearch, MongoDB Atlas |
| Multimodal hoặc image-heavy | LanceDB hoặc Milvus |

## 10. Kết luận

Nếu mới bắt đầu, nên đi theo lộ trình đơn giản trước: hiểu embedding, thử FAISS hoặc Chroma để nắm retrieval pipeline, sau đó chuyển sang Qdrant hoặc pgvector khi cần filtered search, multi-tenant hoặc tích hợp chặt với ứng dụng thực tế.

Trong production, thành công không nằm ở việc chọn đúng một công cụ "hot", mà nằm ở cách bạn kiểm soát embedding, chunking, filtering, recall, chi phí và quy trình reindex.
