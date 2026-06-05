"""S3SourceParser — ingest theo `source_uri=s3://bucket/key` (GCP/GCS qua S3-interop,
R2, MinIO, AWS). BE chỉ gửi URL; parser này TỰ tải về rồi giao cho parser local cũ.

LƯU Ý TÊN GỌI: "S3" ở đây là *giao thức/SDK* (boto3), KHÔNG phải dịch vụ AWS. Backend
do `S3_ENDPOINT_URL` quyết định — PRODUCTION = GCP (Google Cloud Storage) qua API
S3-interoperability: cùng client boto3, chỉ đổi endpoint + dùng HMAC key. Giữ tên S3
(không đổi thành GCS_*) là CHỦ Ý: một client phục vụ GCS/MinIO/R2/AWS, và boto3 chỉ
nói giao thức S3. CI/e2e chạy MinIO (S3-compatible), prod chạy GCS — cùng code đường này.

Trọng tâm: TẢI AN TOÀN, không làm sập server (OOM/đầy đĩa/treo worker). 5 lớp guard:

  1. HEAD trước khi tải  -> biết ContentLength, quá ngưỡng thì từ chối NGAY (ko tải).
  2. Stream xuống file tạm trên đĩa (KHÔNG đọc cả file vào RAM).
  3. Đếm byte khi ghi, vượt ngưỡng -> hủy + xóa (phòng HEAD thiếu/sai size).
  4. Semaphore giới hạn số lượt tải đồng thời (tránh nhiều file lớn cùng lúc).
  5. connect/read timeout + luôn xóa file tạm trong `finally`.

Tải về xong giao cho `LocalFileParser` (download -> local -> parse cũ). Lineage giữ
nguyên URL S3 gốc để search truy ngược đúng nguồn. Non-`s3://` thì uỷ quyền thẳng
cho parser local (S3 parser là superset, an toàn khi config bật mặc định).

Credentials/endpoint đọc từ ENV (secret KHÔNG để trong config.yaml):
  S3_ACCESS_KEY_ID · S3_SECRET_ACCESS_KEY · S3_ENDPOINT_URL · S3_REGION
GCS S3-interop: đặt S3_ENDPOINT_URL=https://storage.googleapis.com + HMAC key.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, Callable

from app.domain.repositories.parser import ParsedArtifact, Parser

_S3_SCHEMES = ("s3://", "gs://")


def _source_root() -> Path:
    return Path(os.getenv("SOURCE_ROOT", os.getcwd())).resolve()


def _max_remote_bytes() -> int:
    # Trần kích thước file tải từ S3. Tách env riêng để chỉnh độc lập với file local.
    raw = os.getenv("MAX_REMOTE_SOURCE_BYTES") or os.getenv(
        "MAX_SOURCE_SIZE_BYTES", str(10 * 1024 * 1024)
    )
    return int(raw)


def _fetch_concurrency() -> int:
    return max(1, int(os.getenv("S3_FETCH_CONCURRENCY", "4")))


def _download_chunk_bytes() -> int:
    return max(64 * 1024, int(os.getenv("S3_DOWNLOAD_CHUNK_BYTES", str(1024 * 1024))))


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def parse_s3_uri(source_uri: str) -> tuple[str, str]:
    """`s3://bucket/key` | `gs://bucket/key` -> (bucket, key). Lỗi nếu thiếu."""
    for scheme in _S3_SCHEMES:
        if source_uri.startswith(scheme):
            rest = source_uri[len(scheme):]
            bucket, _, key = rest.partition("/")
            if not bucket or not key:
                raise ValueError(f"S3 URI thiếu bucket hoặc key: {source_uri!r}")
            return bucket, key
    raise ValueError(f"không phải S3 URI (cần s3:// hoặc gs://): {source_uri!r}")


def _default_client_factory() -> Any:
    try:
        import boto3
        from botocore.client import Config
    except ModuleNotFoundError as exc:  # pragma: no cover - chỉ khi chưa cài boto3
        raise ModuleNotFoundError(
            "S3SourceParser cần boto3. Cài: pip install boto3"
        ) from exc
    base_config = dict(
        signature_version="s3v4",
        connect_timeout=float(os.getenv("S3_CONNECT_TIMEOUT", "10")),
        read_timeout=float(os.getenv("S3_READ_TIMEOUT", "60")),
        retries={"max_attempts": int(os.getenv("S3_MAX_ATTEMPTS", "3"))},
    )
    # GCS/R2/MinIO từ chối flexible-checksum header của botocore -> tắt. Chỉ botocore
    # >=1.36 mới có 2 tham số này; bản cũ (vd boto3 1.35.x) sẽ raise TypeError -> fallback.
    try:
        config = Config(
            **base_config,
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        )
    except TypeError:
        config = Config(**base_config)
    return boto3.client(
        "s3",
        endpoint_url=_env("S3_ENDPOINT_URL", "R2_ENDPOINT_URL") or None,
        aws_access_key_id=_env("S3_ACCESS_KEY_ID", "R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_env("S3_SECRET_ACCESS_KEY", "R2_SECRET_ACCESS_KEY"),
        region_name=_env("S3_REGION", default="auto"),
        config=config,
    )


class S3SourceParser(Parser):
    def __init__(
        self,
        inner: Parser,
        *,
        client_factory: Callable[[], Any] | None = None,
        max_bytes: int | None = None,
        concurrency: int | None = None,
    ) -> None:
        self._inner = inner
        self._client_factory = client_factory or _default_client_factory
        self._client: Any | None = None
        self._max_bytes = max_bytes if max_bytes is not None else _max_remote_bytes()
        self._semaphore = asyncio.Semaphore(
            concurrency if concurrency is not None else _fetch_concurrency()
        )

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    async def parse(
        self,
        *,
        document_id: str,
        file_type: str,
        source_uri: str,
    ) -> ParsedArtifact:
        # Non-S3 -> uỷ quyền thẳng parser local (superset, không đổi hành vi cũ).
        if not source_uri.startswith(_S3_SCHEMES):
            return await self._inner.parse(
                document_id=document_id,
                file_type=file_type,
                source_uri=source_uri,
            )

        bucket, key = parse_s3_uri(source_uri)
        suffix = (file_type or Path(key).suffix).lstrip(".")
        root = _source_root()
        root.mkdir(parents=True, exist_ok=True)
        temp_name = f".s3-{uuid.uuid4().hex}.{suffix}" if suffix else f".s3-{uuid.uuid4().hex}"
        temp_path = root / temp_name
        try:
            async with self._semaphore:  # lớp 4: giới hạn tải đồng thời
                await asyncio.to_thread(
                    self._download_guarded, bucket, key, temp_path
                )
            # Tải xong: parser local đọc bản local (giữ nguyên logic OCR/format).
            artifact = await self._inner.parse(
                document_id=document_id,
                file_type=file_type,
                source_uri=f"local://{temp_name}",
            )
        finally:
            try:  # lớp 5: luôn dọn file tạm
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        # Lineage trỏ về URL S3 gốc, không phải file tạm.
        return ParsedArtifact(markdown=artifact.markdown, source_uri=source_uri)

    def _download_guarded(self, bucket: str, key: str, dest: Path) -> None:
        client = self._get_client()
        # Lớp 1: HEAD trước -> quá ngưỡng thì KHÔNG tải.
        head = client.head_object(Bucket=bucket, Key=key)
        size = int(head.get("ContentLength", 0))
        if size > self._max_bytes:
            raise ValueError(
                f"S3 object {bucket}/{key} = {size} bytes > "
                f"MAX_REMOTE_SOURCE_BYTES ({self._max_bytes}); từ chối tải."
            )
        # Lớp 2+3: stream xuống đĩa, đếm byte, chặn cứng giữa chừng.
        body = client.get_object(Bucket=bucket, Key=key)["Body"]
        written = 0
        chunk_size = _download_chunk_bytes()
        try:
            with open(dest, "wb") as fh:
                while True:
                    chunk = body.read(chunk_size)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > self._max_bytes:
                        raise ValueError(
                            f"S3 object {bucket}/{key} vượt "
                            f"MAX_REMOTE_SOURCE_BYTES ({self._max_bytes}) khi đang tải; hủy."
                        )
                    fh.write(chunk)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

    def close(self) -> None:
        inner_close = getattr(self._inner, "close", None)
        if callable(inner_close):
            inner_close()
