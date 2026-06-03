from fastapi.testclient import TestClient

from app.application.use_cases.ingestion import IngestDocumentUseCase
from app.interfaces.api.dependencies import get_ingest_use_case
from app.interfaces.api.main import app


class StubIngestUseCase(IngestDocumentUseCase):
    def __init__(self) -> None:
        self.ingest_calls = []
        self.delete_calls = []

    async def ingest(self, **kwargs):
        self.ingest_calls.append(kwargs)
        return 2

    async def delete(self, document_id: str) -> None:
        self.delete_calls.append(document_id)


def test_ingest_router_accepts_markdown_payload() -> None:
    stub = StubIngestUseCase()
    app.dependency_overrides[get_ingest_use_case] = lambda: stub

    with TestClient(app) as client:
        response = client.post(
            "/api/ingest",
            json={
                "document_id": "doc-1",
                "document_name": "Guide",
                "file_type": "md",
                "markdown": "# Title\nBody",
                "source_uri": "local://doc-1",
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert stub.ingest_calls[0]["document_id"] == "doc-1"
    assert response.json()["chunk_count"] == 2


def test_delete_ingest_router_deletes_document() -> None:
    stub = StubIngestUseCase()
    app.dependency_overrides[get_ingest_use_case] = lambda: stub

    with TestClient(app) as client:
        response = client.delete("/api/ingest/doc-9")

    app.dependency_overrides.clear()

    assert response.status_code == 204
    assert stub.delete_calls == ["doc-9"]
