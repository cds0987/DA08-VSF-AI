from __future__ import annotations

import asyncio
import threading
from datetime import UTC
from typing import Any, Callable

from app.domain.repositories.object_store_lister import ObjectStoreLister, StoredObject
from app.infrastructure.external.s3_parser import _default_client_factory


def _as_aware_utc(value) -> object:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class S3ObjectStoreLister(ObjectStoreLister):
    def __init__(
        self,
        *,
        bucket: str,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._bucket = bucket
        self._client_factory = client_factory or _default_client_factory
        self._client: Any | None = None
        self._client_lock = threading.Lock()

    def _get_client(self) -> Any:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    self._client = self._client_factory()
        return self._client

    def _list_objects_page(
        self,
        *,
        prefix: str,
        continuation_token: str | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
        if continuation_token:
            params["ContinuationToken"] = continuation_token
        return self._get_client().list_objects_v2(**params)

    async def list_objects(self, prefix: str):
        continuation_token: str | None = None
        while True:
            page = await asyncio.to_thread(
                self._list_objects_page,
                prefix=prefix,
                continuation_token=continuation_token,
            )
            for entry in page.get("Contents", []):
                last_modified = _as_aware_utc(entry.get("LastModified"))
                if last_modified is None:
                    continue
                yield StoredObject(
                    key=str(entry.get("Key") or ""),
                    size=int(entry.get("Size") or 0),
                    last_modified=last_modified,
                )
            if not page.get("IsTruncated"):
                return
            continuation_token = page.get("NextContinuationToken")
