# S3 client: botocore checksum kwargs + lưu ý chạy production thật

> Ghi lại bug lộ ra khi chạy **e2e thật** đầu tiên (rag-worker tải file từ MinIO/S3 thật
> trong CI), và các lưu ý khi đưa nguồn S3/GCS lên production. Liên quan:
> [ingest-transport.md](ingest-transport.md) (cửa vào ingest), `app/infrastructure/external/s3_parser.py`.

## 1. Triệu chứng

E2e (`tests/e2e/test_nats_protocol_e2e.py`) fail ngay khi tạo S3 client:

```
TypeError: Got unexpected keyword argument 'request_checksum_calculation'
  app/infrastructure/external/s3_parser.py  -> _default_client_factory()
  botocore/config.py:308
```

Toàn bộ luồng ingest qua NATS đứng ở bước fetch file (chưa parse được gì).

## 2. Nguyên nhân gốc

`_default_client_factory()` tạo `botocore.client.Config` với 2 tham số:

```python
request_checksum_calculation="when_required",
response_checksum_validation="when_required",
```

Hai tham số này **chỉ tồn tại từ botocore >= 1.36** (đợt AWS đổi sang *flexible checksum*).
`requirements.txt` đang ghim **`boto3==1.35.99`** → kéo theo **botocore 1.35.x** → chưa có
2 kwarg đó → `Config(...)` raise `TypeError`.

**Vì sao trước đó không ai phát hiện:** mọi unit/integration test cũ của S3 parser đều
**inject `client_factory` giả** (không gọi `_default_client_factory` thật). Hàm tạo client
thật **chưa từng được chạy** trong test cho tới khi có e2e tải file từ MinIO thật. Đây là
bug production tiềm ẩn — nếu deploy với botocore 1.35, **mọi ingest nguồn S3 đều crash**.

## 3. Fix

Truyền 2 kwarg checksum **chỉ khi botocore hỗ trợ**, fallback nếu không
(`_default_client_factory` trong `s3_parser.py`):

```python
base_config = dict(signature_version="s3v4", connect_timeout=..., read_timeout=..., retries=...)
try:
    config = Config(**base_config,
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required")
except TypeError:
    config = Config(**base_config)   # botocore < 1.36
```

Hoạt động trên cả botocore cũ (1.35, fallback) lẫn mới (>=1.36, có tắt checksum).

## 4. Vì sao 2 kwarg checksum này quan trọng (KHÔNG được bỏ hẳn)

Từ botocore 1.36, mặc định client **tự thêm header flexible-checksum** (`x-amz-checksum-*`)
vào request. **GCS (S3-interop), Cloudflare R2, một số bản MinIO TỪ CHỐI** header này →
upload/get lỗi `400`/`501`/checksum mismatch. Đặt `when_required` để **tắt** checksum mặc
định, chỉ bật khi thực sự cần. Vì vậy:

- Chạy với **botocore >= 1.36 + GCS/R2/MinIO**: BẮT BUỘC giữ 2 kwarg (đang có).
- Chạy với **botocore < 1.36**: không có checksum mặc định nên không cần (fallback an toàn).

→ Đừng "dọn" `try/except` thành bỏ luôn 2 kwarg: sẽ vỡ trên botocore mới + GCS/R2.

## 5. Lưu ý khi chạy production THẬT

### 5.1 Phiên bản botocore/boto3
- Khuyến nghị **nâng pin lên `boto3 >= 1.36`** (kèm botocore >=1.36) để dùng đúng nhánh
  tắt-checksum, thay vì dựa vào fallback. Nếu vẫn giữ 1.35.x thì fallback chạy được nhưng
  bạn **mất** khả năng tắt checksum — chỉ an toàn vì botocore 1.35 chưa bật checksum mặc định.
- Sau khi đổi version, **chạy lại e2e** (`tests/e2e/test_nats_protocol_e2e.py`) — đây là test
  DUY NHẤT gọi `_default_client_factory` thật.

### 5.2 ENV bắt buộc (rag-worker đọc `S3_*`, không phải `AWS_*`)
```
PARSER_IMPL=s3
S3_ENDPOINT_URL=...        # GCS: https://storage.googleapis.com | R2: https://<acct>.r2.cloudflarestorage.com | MinIO: http://minio:9000
S3_ACCESS_KEY_ID=...       # GCS dùng HMAC key
S3_SECRET_ACCESS_KEY=...
S3_REGION=...              # AWS: vùng thật; GCS/R2/MinIO: 'auto' hoặc 'us-east-1'
```
> ⚠️ document-service đọc storage bằng bộ biến **`AWS_*`** khác — hai service phải trỏ
> **cùng bucket/endpoint/credentials**. Xem `docs/sync-doc-ingest-rag-worker.md §3` (repo gốc).

### 5.3 Quy ước giá trị `gcs_key` trong `doc.ingest`
- Phải là **URI đầy đủ**: `s3://bucket/key` hoặc `gs://bucket/key` (parser nhận cả hai).
- KHÔNG gửi key tương đối (`raw/<id>/<name>`) — parser không tự ghép bucket.

### 5.4 Tên collection Qdrant
- Engine đặt collection = **`{VECTOR_COLLECTION}__{model_tag}__d{dimension}`**
  (vd `rag_chatbot__te3s__d1536`), KHÔNG phải tên trần.
- Khi thao tác/monitor Qdrant trực tiếp, resolve theo prefix hoặc kèm đầy đủ hậu tố model+dim.
- Cùng dimension nhưng khác model vẫn ra collection khác, nên không còn đè/đọc nhầm vector.

### 5.5 Giới hạn tải an toàn (đã có guard trong `s3_parser.py`)
- `MAX_REMOTE_SOURCE_BYTES` / `MAX_SOURCE_SIZE_BYTES`: trần kích thước file (HEAD trước khi tải).
- `S3_FETCH_CONCURRENCY`, `S3_CONNECT_TIMEOUT`, `S3_READ_TIMEOUT`, `S3_MAX_ATTEMPTS`: chỉnh theo tải production.

## 6. Bài học

Test inject fake luôn xanh **không chứng minh** code tạo-client thật chạy được. Mọi
"composition root" (factory tạo client thật từ ENV) cần ít nhất **một e2e chạm hạ tầng thật**
trong CI. Xem thêm [native-deps.md](native-deps.md) cho lớp lỗi tương tự (native deps chỉ lộ khi chạy thật).
