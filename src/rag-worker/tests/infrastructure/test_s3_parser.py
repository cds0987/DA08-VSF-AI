from __future__ import annotations

import pytest

from app.infrastructure.external.local_parser import LocalFileParser
from app.infrastructure.external.s3_parser import S3SourceParser, parse_s3_uri


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self.closed = False

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            chunk = self._data[self._pos:]
        else:
            chunk = self._data[self._pos: self._pos + n]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class _FakeClient:
    """S3 client giả: head_object trả size khai báo, get_object stream data thật."""

    def __init__(self, data: bytes, head_size: int | None = None) -> None:
        self._data = data
        self._head_size = head_size if head_size is not None else len(data)
        self.head_calls = 0
        self.get_calls = 0

    def head_object(self, *, Bucket: str, Key: str) -> dict:
        self.head_calls += 1
        return {"ContentLength": self._head_size}

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        self.get_calls += 1
        return {"Body": _FakeBody(self._data)}


def _inner() -> LocalFileParser:
    return LocalFileParser(max_workers=1)


def test_parse_s3_uri() -> None:
    assert parse_s3_uri("s3://bucket/dir/file.pdf") == ("bucket", "dir/file.pdf")
    assert parse_s3_uri("gs://b/k") == ("b", "k")
    with pytest.raises(ValueError):
        parse_s3_uri("https://host/x")
    with pytest.raises(ValueError):
        parse_s3_uri("s3://bucket-only")  # thiếu key


@pytest.mark.asyncio
async def test_downloads_and_parses_then_cleans_temp(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_ROOT", str(tmp_path))
    client = _FakeClient(b"# Title\nhello world content")
    parser = S3SourceParser(_inner(), client_factory=lambda: client)

    artifact = await parser.parse(
        document_id="d1", file_type="md", source_uri="s3://bucket/key.md"
    )

    assert "hello world content" in artifact.markdown
    assert artifact.source_uri == "s3://bucket/key.md"  # lineage = URL gốc
    assert client.head_calls == 1 and client.get_calls == 1
    assert not list(tmp_path.glob(".s3-*")), "file tạm phải được dọn"


@pytest.mark.asyncio
async def test_rejects_oversize_via_head_without_downloading(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_ROOT", str(tmp_path))
    client = _FakeClient(b"x" * 50, head_size=10**9)  # HEAD báo file khổng lồ
    parser = S3SourceParser(_inner(), client_factory=lambda: client, max_bytes=100)

    with pytest.raises(ValueError, match="MAX_REMOTE_SOURCE_BYTES"):
        await parser.parse(document_id="d1", file_type="md", source_uri="s3://b/k.md")

    assert client.get_calls == 0, "quá ngưỡng ở HEAD thì KHÔNG được tải"
    assert not list(tmp_path.glob(".s3-*"))


@pytest.mark.asyncio
async def test_hard_caps_when_head_lies_about_size(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_ROOT", str(tmp_path))
    # HEAD nói nhỏ (qua được lớp 1) nhưng body thật lớn -> phải chặn cứng khi stream.
    client = _FakeClient(b"x" * 1000, head_size=1)
    parser = S3SourceParser(_inner(), client_factory=lambda: client, max_bytes=100)

    with pytest.raises(ValueError, match="MAX_REMOTE_SOURCE_BYTES"):
        await parser.parse(document_id="d1", file_type="md", source_uri="s3://b/k.md")

    assert not list(tmp_path.glob(".s3-*")), "file tạm dở dang phải bị xóa"


@pytest.mark.asyncio
async def test_non_s3_uri_delegates_to_inner(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_ROOT", str(tmp_path))
    (tmp_path / "a.md").write_text("# H\nlocal content here", encoding="utf-8")

    def _no_client():
        raise AssertionError("non-S3 không được dựng S3 client")

    parser = S3SourceParser(_inner(), client_factory=_no_client)
    artifact = await parser.parse(
        document_id="d", file_type="md", source_uri="local://a.md"
    )
    assert "local content here" in artifact.markdown
