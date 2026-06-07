from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.infrastructure.external.object_store_lister import S3ObjectStoreLister


class _PagedClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def list_objects_v2(self, **kwargs):
        self.calls.append(dict(kwargs))
        if len(self.calls) == 1:
            return {
                "Contents": [
                    {
                        "Key": "raw/doc-1/file.pdf",
                        "Size": 10,
                        "LastModified": datetime(2026, 1, 1, tzinfo=UTC),
                    }
                ],
                "IsTruncated": True,
                "NextContinuationToken": "page-2",
            }
        return {
            "Contents": [
                {
                    "Key": "raw/doc-2/file.pdf",
                    "Size": 20,
                    "LastModified": datetime(2026, 1, 2, tzinfo=UTC),
                }
            ],
            "IsTruncated": False,
        }


@pytest.mark.asyncio
async def test_s3_object_store_lister_pages_until_exhausted() -> None:
    client = _PagedClient()
    lister = S3ObjectStoreLister(bucket="docs", client_factory=lambda: client)

    objects = [obj async for obj in lister.list_objects("raw/")]

    assert [obj.key for obj in objects] == ["raw/doc-1/file.pdf", "raw/doc-2/file.pdf"]
    assert client.calls == [
        {"Bucket": "docs", "Prefix": "raw/"},
        {"Bucket": "docs", "Prefix": "raw/", "ContinuationToken": "page-2"},
    ]
