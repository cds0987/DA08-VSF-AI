from __future__ import annotations

import asyncio
import hashlib
import threading
from typing import Any, Callable

from app.domain.repositories.artifact_store import ArtifactStore
from app.infrastructure.external.s3_parser import (
    _default_client_factory,
    current_source_bucket,
    parse_s3_uri,
)


def _safe_document_id(document_id: str) -> str:
    cleaned = document_id.strip()
    if cleaned and all(ch.isalnum() or ch in "-_" for ch in cleaned):
        return cleaned
    digest = hashlib.sha256(document_id.encode("utf-8")).hexdigest()
    return f"doc-{digest}"


class S3ArtifactStore(ArtifactStore):
    def __init__(
        self,
        *,
        bucket: str | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._bucket = (bucket or current_source_bucket()).strip()
        if not self._bucket:
            raise ValueError("artifact store requires a source bucket")
        self._client_factory = client_factory or _default_client_factory
        self._client: Any | None = None
        self._client_lock = threading.Lock()

    def _get_client(self) -> Any:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    self._client = self._client_factory()
        return self._client

    def _artifact_key(self, document_id: str) -> str:
        return f"artifacts/{_safe_document_id(document_id)}/markdown.md"

    async def write_markdown(self, document_id: str, markdown: str) -> str:
        key = self._artifact_key(document_id)
        await asyncio.to_thread(
            self._get_client().put_object,
            Bucket=self._bucket,
            Key=key,
            Body=markdown.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
        )
        return f"s3://{self._bucket}/{key}"

    async def read_markdown(self, artifact_uri: str) -> str:
        bucket, key = parse_s3_uri(artifact_uri)
        response = await asyncio.to_thread(
            self._get_client().get_object,
            Bucket=bucket,
            Key=key,
        )
        body = response["Body"]
        try:
            payload = await asyncio.to_thread(body.read)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        return payload.decode("utf-8")

    async def delete_by_document(self, document_id: str) -> None:
        key = self._artifact_key(document_id)
        await asyncio.to_thread(
            self._get_client().delete_object,
            Bucket=self._bucket,
            Key=key,
        )
