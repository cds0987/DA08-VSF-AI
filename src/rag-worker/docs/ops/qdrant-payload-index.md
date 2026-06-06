# Qdrant: payload index bắt buộc cho field filter (Qdrant Cloud)

> Ghi lại bug lộ ra khi chạy **e2e thật trên Qdrant Cloud** với collection TẠO MỚI
> (sau khi xóa sạch collection cũ). Liên quan:
> `core_engine/vectorstore/providers/qdrant/remote.py` + `.../inprocess.py`,
> [search-split-vectorstore-contract.md](../search-split-vectorstore-contract.md).

## 1. Triệu chứng

Sau khi clean Qdrant Cloud rồi chạy lại, **mọi job ingest đều `status=failed`**, Qdrant
`points_count=0`. Log rag-worker spam:

```
HTTP Request: POST .../collections/rag_chatbot__te3s__d1536/points/scroll
  "HTTP/1.1 400 Bad Request"
```

Gọi thẳng scroll trả lý do thật:

```json
{"status":{"error":"Bad request: Index required but not found for \"document_id\"
  of one of the following types: [keyword]. Help: Create an index for this key
  or use a different filter."}}
```

## 2. Nguyên nhân gốc

- rag-worker filter theo `document_id` ở 3 chỗ: **dedup scroll** (chống NATS redelivery,
  `list_chunk_ids_by_document`), **delete** (`doc.access{deleted:true}`), và **scoped
  search** (mcp truyền `document_ids`).
- **Qdrant Cloud bật "indexing required for filtering"** → filter trên field CHƯA có
  payload index ⇒ **400**, không phải scan ngầm như Qdrant tự host mặc định.
- Code tạo collection (`_ensure()`) trước đây CHỈ tạo `vectors_config`, **không tạo payload
  index**. Bug bị che vì collection cũ (tạo bởi lần chạy trước) đã sẵn index — chỉ khi
  **tạo collection mới từ đầu** mới lộ.

> Nghịch lý điển hình: "đang chạy ngon" chỉ vì state cũ còn sót. Xóa sạch để test lại mới
> ra sự thật.

## 3. Cách sửa

Tạo **keyword payload index** cho `document_id` NGAY sau `create_collection`, ở cả 2
provider (`remote` async + `inprocess` sync):

```python
await self._client.create_collection(collection_name=..., vectors_config=...)
await self._client.create_payload_index(
    collection_name=...,
    field_name="document_id",
    field_schema=models.PayloadSchemaType.KEYWORD,
)
```

Chỉ chạy trong nhánh `if not collection_exists` → idempotent, không đụng collection có sẵn.

Kết quả sau fix (clean GCS + Qdrant rồi chạy lại): **ingest 9/9 completed, search 6/6**.

## 4. Quy tắc phòng ngừa

1. **Mọi field dùng để filter trên Qdrant Cloud PHẢI có payload index** — tạo cùng lúc tạo
   collection, đừng giả định Qdrant tự scan. Thêm field filter mới (vd `classification`,
   `allowed_user_ids`) ⇒ thêm index tương ứng.
2. **Test trên collection TẠO MỚI**, không chỉ trên state cũ — bug schema/index chỉ lộ khi
   bootstrap từ rỗng. Trước khi tin "pass", clean vectorstore rồi chạy lại.
3. Đọc **error body** của Qdrant (không chỉ status 400) — nó nói thẳng thiếu index field nào.
4. mcp-service (consumer) chỉ verify contract + đọc; index do **rag-worker (producer)** tạo
   lúc dựng collection. Nếu đổi sang để DevOps provision collection sẵn, nhớ kèm bước tạo
   index này.
