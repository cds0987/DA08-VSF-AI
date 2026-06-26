"""S3StorageClient — backend lưu trữ qua giao thức S3 (boto3).

Cùng interface với GCSClient (upload/delete/presigned/object_uri) để inject thay thế
trực tiếp qua get_storage(). "S3" = giao thức/SDK, KHÔNG phải dịch vụ AWS: endpoint do
S3_ENDPOINT_URL quyết định — local/e2e chạy MinIO, prod có thể là GCS S3-interop/R2/AWS.

object_uri() trả `s3://bucket/key` — rag-worker S3SourceParser parse được cả s3:// lẫn
gs://, nên cú bắt tay document-service -> rag-worker giữ nguyên.

Config khớp với rag-worker s3_parser: signature s3v4 + tắt flexible-checksum (MinIO/R2/GCS
từ chối header này của botocore >=1.36).
"""

from __future__ import annotations

import asyncio

from app.core.config import Settings


class S3StorageClient:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self._endpoint_url = settings.s3_endpoint_url or None
        self._access_key = settings.s3_access_key_id
        self._secret_key = settings.s3_secret_access_key
        self._region = settings.s3_region
        self._client = self._build_client()

    async def upload_file(self, key: str, content: bytes, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=content,
            **extra,
        )

    async def delete_file(self, key: str) -> None:
        await asyncio.to_thread(
            self._client.delete_object,
            Bucket=self.bucket,
            Key=key,
        )

    async def download_file(self, key: str) -> bytes:
        def _download() -> bytes:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()

        return await asyncio.to_thread(_download)

    async def generate_presigned_url(self, key: str, expires_in: int = 300) -> str:
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def object_uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def _build_client(self):
        try:
            import boto3
            from botocore.client import Config
        except ImportError as exc:
            raise RuntimeError("boto3 is required for S3 storage backend") from exc

        # path-style addressing: MinIO/local không có DNS cho virtual-host
        # (bucket.endpoint) -> bắt buộc path-style (endpoint/bucket/key).
        base_config = dict(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        )
        # MinIO/R2/GCS từ chối flexible-checksum của botocore >=1.36 -> tắt. Bản cũ raise
        # TypeError vì chưa có 2 tham số này -> fallback.
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
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key or None,
            aws_secret_access_key=self._secret_key or None,
            region_name=self._region or "auto",
            config=config,
        )
