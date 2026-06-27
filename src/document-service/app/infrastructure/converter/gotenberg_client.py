import logging
import time

import httpx

from app.application.exceptions import ConversionError

logger = logging.getLogger(__name__)

_CONVERT_PATH = "/forms/libreoffice/convert"


class GotenbergClient:
    """Convert office -> PDF qua Gotenberg LibreOffice route.

    Timeout rõ ràng tránh treo request. KHÔNG log nội dung tài liệu (chỉ status/latency).
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=5.0)
        self._client = client

    async def convert_to_pdf(self, content: bytes, filename: str) -> bytes:
        url = f"{self._base_url}{_CONVERT_PATH}"
        files = {"files": (filename, content)}
        started = time.monotonic()
        try:
            if self._client is not None:
                resp = await self._client.post(url, files=files)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(url, files=files)
        except httpx.HTTPError as exc:
            logger.warning("gotenberg request failed: %s", type(exc).__name__)
            raise ConversionError("gotenberg request failed") from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code // 100 != 2:
            logger.warning("gotenberg non-2xx status=%s latency_ms=%s", resp.status_code, latency_ms)
            raise ConversionError(f"gotenberg status {resp.status_code}")

        pdf = resp.content
        if pdf[:5] != b"%PDF-":
            logger.warning("gotenberg returned non-PDF bytes latency_ms=%s", latency_ms)
            raise ConversionError("gotenberg returned non-PDF content")
        return pdf
