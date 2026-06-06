# mcp-service - Security Hardening

> Pham vi: chi `mcp-service`.
> Service nay la reader read-only cho Qdrant, expose 1 MCP tool `rag_search` qua Streamable HTTP.

## Tong quan

Pipeline 1 request:

`embed(query) -> Qdrant search(top_k_candidates) -> rerank -> top_k`

Code chinh:

- Entry + fail-closed startup: [`app/main.py`](../app/main.py)
- MCP tool: [`app/interfaces/mcp_server.py`](../app/interfaces/mcp_server.py)
- Orchestration: [`app/core/search.py`](../app/core/search.py)
- Qdrant reader: [`app/core/vectorstore.py`](../app/core/vectorstore.py)
- Embedder: [`app/core/embedding.py`](../app/core/embedding.py)
- Reranker: [`app/core/rerank.py`](../app/core/rerank.py)

Contract fail-closed va fingerprint stamp van duoc giu nguyen. Khong sua logic nay.

## Trang thai hien tai

### Da xu ly trong code

1. `document_ids` khong con la no-op.
   `rag_search -> SearchService -> QdrantReader` da truyen `document_ids` xuong `query_filter` cua Qdrant theo payload key `document_id`.

2. Da bo log "ACL filtering is owned by another service".
   Service nay gio tu enforce scope khi caller truyen allow-list.

3. Da them connection pooling cho client remote.
   `AsyncQdrantClient`, OpenAI embed client, va OpenAI rerank client deu duoc lazy-init 1 lan va tai su dung.
   Sau startup verify, service dong cac pooled client nay ngay de event loop phuc vu co the tao lai client gan dung loop cua no.

4. Da bo round-trip thua trong `_search_remote`.
   Khong check `collection_exists()` truoc moi request nua; startup da verify fail-closed.

5. `top_k` cua MCP tool da doi ve `None` by default.
   Luc caller khong truyen `top_k`, service se fallback ve `rerank_top_k` trong config.

6. Da them note `nosec` cho `md5` trong offline hash embed.
   Day la hash tat dinh cho embedding, khong phai primitive bao mat.

7. Da clamp `top_k` trong service.
   Ket qua cuoi cung bi gioi han trong khoang `1..top_k_candidates`.

8. Test da duoc cap nhat.
   `pytest src/mcp-service/tests -q` dang pass `21/21`.

### Chua xu ly trong code nay

1. Authentication/network hardening cho MCP endpoint.
   Day la bai toan deploy, khong nam tron trong source `mcp-service`.

2. Payload index cho `document_id` tren Qdrant.
   Nen duoc tao o producer (`rag-worker`) khi tao collection de filter nhanh hon.

## Chi tiet tung muc

### 1. ACL truoc Qdrant

Van de cu:

- Tool nhan `document_ids` nhung khong filter.
- Query-service co post-filter lai, nhung van chua dat `ACL-before-Qdrant`.

Trang thai moi:

- `QdrantReader._build_filter()` tao `models.Filter`.
- `query_points(..., query_filter=...)` duoc ap dung cho ca remote va local path.
- `SearchService.rag_search()` truyen `document_ids` xuong reader.

Tac dong:

- Giam nguy co cross-document leak.
- Khop hon voi ky vong contract cua `query-service`.

Luu y:

- De duoc nhanh, can payload index `document_id` ben `rag-worker`.

### 2. Auth/network

Van de:

- Endpoint bind `0.0.0.0:8003`.
- Khong co token, mTLS, hay middleware auth.

Khuyen nghi deploy:

- Khong expose public.
- Neu chay tren Kubernetes, chi dung `Service` type `ClusterIP`.
- Them `NetworkPolicy` chi cho `query-service` vao port `8003`.

Mau:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: mcp-service-allow-query-only
spec:
  podSelector:
    matchLabels:
      app: mcp-service
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: query-service
      ports:
        - protocol: TCP
          port: 8003
```

Neu khong kiem soat duoc network, co the them shared-secret header o ASGI layer. Viec nay chua lam trong thay doi hien tai.

### 3. Connection pooling

Van de cu:

- Moi request tao/dong lai Qdrant client.
- Moi request tao/dong lai OpenAI client cho embed va rerank.

Trang thai moi:

- Cac client duoc lazy-init va giu trong object song suot process.
- Co `aclose()` de cleanup luc shutdown neu runtime goi duoc.
- Startup verify khong de lai pooled client song qua doi event loop:
  `main.py` verify xong se `aclose()` ngay trong cung `asyncio.run(...)`, roi serving loop moi lazy-init lai.

### 4. Double round-trip

Van de cu:

- `_search_remote()` check `collection_exists()` truoc `query_points()`.

Trang thai moi:

- Goi truc tiep `query_points()`.
- Neu collection bien mat sau startup verify thi request fail la hop ly.

### 5. Don dep nho

- `rerank_top_k` khong con bi "chet" tren duong MCP.
- `top_k` duoc clamp thay vi de caller truyen so bat ky.
- `md5` co suppression comment ro nghia.

## Kiem tra sau sua

Da doc va doi chieu voi `query-service`:

- [`src/query-service/app/infrastructure/external/mcp_client.py`](../../query-service/app/infrastructure/external/mcp_client.py)
- [`src/query-service/app/application/use_cases/query/orchestration.py`](../../query-service/app/application/use_cases/query/orchestration.py)

Ket luan:

- `query-service` dang truyen `document_ids` tu allow-list that su.
- No van post-filter lai ket qua de phong thu.
- Truoc thay doi nay, `mcp-service` chua enforce scope truoc Qdrant.
- Sau thay doi nay, caller va callee da thong nhat hon ve contract.

## Viec tiep theo de xong hardening

1. Them payload index `document_id` trong `rag-worker` khi tao collection.
2. Khoa network cua `mcp-service` o tang deploy.
3. Neu production can auth o application layer, bo sung middleware kiem tra header noi bo hoac mTLS.
