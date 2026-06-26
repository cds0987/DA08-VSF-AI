from typing import Protocol


class DocumentConverter(Protocol):
    """Port convert office -> PDF. Impl hạ tầng: GotenbergClient."""

    async def convert_to_pdf(self, content: bytes, filename: str) -> bytes:
        ...
