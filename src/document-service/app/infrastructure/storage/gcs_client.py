import asyncio
from datetime import timedelta

from app.core.config import Settings


class GCSClient:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.gcs_bucket
        self.project_id = settings.gcp_project_id
        self._client = None
        self._bucket = None

    async def upload_file(self, key: str, content: bytes, content_type: str | None = None) -> None:
        blob = self._get_bucket().blob(key)
        await asyncio.to_thread(blob.upload_from_string, content, content_type=content_type)

    async def delete_file(self, key: str) -> None:
        blob = self._get_bucket().blob(key)
        await asyncio.to_thread(blob.delete)

    async def download_file(self, key: str) -> bytes:
        blob = self._get_bucket().blob(key)
        return await asyncio.to_thread(blob.download_as_bytes)

    async def generate_presigned_url(self, key: str, expires_in: int = 300) -> str:
        blob = self._get_bucket().blob(key)
        return await asyncio.to_thread(self._sign_url, blob, expires_in)

    def _sign_url(self, blob, expires_in: int) -> str:
        base = dict(
            version="v4",
            expiration=timedelta(seconds=expires_in),
            method="GET",
        )
        try:
            # Local/dev: credentials carry a private key -> sign locally.
            return blob.generate_signed_url(**base)
        except AttributeError:
            # Prod keyless (VM-attached SA via ADC): credentials hold only a token,
            # no private key, so V4 signing must go through the IAM signBlob API.
            email, token = self._iam_signer()
            return blob.generate_signed_url(
                **base, service_account_email=email, access_token=token
            )

    def _iam_signer(self) -> tuple[str, str]:
        import google.auth.transport.requests as grequests

        credentials = self._client._credentials
        credentials.refresh(grequests.Request())
        email = getattr(credentials, "service_account_email", None)
        if not email or email == "default":
            import urllib.request

            req = urllib.request.Request(
                "http://metadata.google.internal/computeMetadata/v1/instance/"
                "service-accounts/default/email",
                headers={"Metadata-Flavor": "Google"},
            )
            email = urllib.request.urlopen(req, timeout=5).read().decode().strip()
        return email, credentials.token

    def object_uri(self, key: str) -> str:
        return f"gs://{self.bucket}/{key}"

    def _get_bucket(self):
        if self._bucket is None:
            self._client = self._build_client()
            self._bucket = self._client.bucket(self.bucket)
        return self._bucket

    def _build_client(self):
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise RuntimeError("google-cloud-storage is required for GCS storage") from exc

        return storage.Client(project=self.project_id or None)
