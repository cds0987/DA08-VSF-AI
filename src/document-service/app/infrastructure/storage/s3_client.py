from io import BytesIO
import os

from app.core.config import Settings


class S3Client:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.aws_s3_bucket
        self.region = settings.aws_region
        self._client = self._build_client(settings)

    async def upload_file(self, key: str, content: bytes, content_type: str | None = None) -> None:
        extra_args = {"ContentType": content_type} if content_type else None
        kwargs = {"Bucket": self.bucket, "Key": key, "Fileobj": BytesIO(content)}
        if extra_args:
            kwargs["ExtraArgs"] = extra_args
        self._client.upload_fileobj(**kwargs)

    async def delete_file(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    async def generate_presigned_url(self, key: str, expires_in: int = 300) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def _build_client(self, settings: Settings):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required for S3 storage") from exc

        return boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            endpoint_url=os.getenv("AWS_S3_ENDPOINT_URL", "http://localhost:9000")
        )

