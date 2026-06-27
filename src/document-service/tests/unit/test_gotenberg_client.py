import httpx
import pytest

from app.application.exceptions import ConversionError
from app.infrastructure.converter.gotenberg_client import GotenbergClient


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_convert_returns_pdf_bytes_on_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/forms/libreoffice/convert"
        return httpx.Response(200, content=b"%PDF-1.7 converted")

    gotenberg = GotenbergClient("http://gotenberg:3000", client=_client(handler))
    out = await gotenberg.convert_to_pdf(b"docx-bytes", "report.docx")
    assert out == b"%PDF-1.7 converted"


@pytest.mark.asyncio
async def test_convert_raises_on_non_2xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"busy")

    gotenberg = GotenbergClient("http://gotenberg:3000", client=_client(handler))
    with pytest.raises(ConversionError):
        await gotenberg.convert_to_pdf(b"x", "a.docx")


@pytest.mark.asyncio
async def test_convert_raises_when_output_not_pdf() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not a pdf")

    gotenberg = GotenbergClient("http://gotenberg:3000", client=_client(handler))
    with pytest.raises(ConversionError):
        await gotenberg.convert_to_pdf(b"x", "a.docx")


@pytest.mark.asyncio
async def test_convert_raises_on_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    gotenberg = GotenbergClient("http://gotenberg:3000", client=_client(handler))
    with pytest.raises(ConversionError):
        await gotenberg.convert_to_pdf(b"x", "a.docx")
