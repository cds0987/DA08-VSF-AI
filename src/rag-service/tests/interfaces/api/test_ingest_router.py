from fastapi.testclient import TestClient

from app.application.use_cases.ingestion import IngestDocumentUseCase
from app.interfaces.api.dependencies import get_ingest_use_case
from app.interfaces.api.main import app


class StubIngestUseCase(IngestDocumentUseCase):
    def __init__(self) -> None:
        self.ingest_calls = []
        self.delete_calls = []
        self.documents = {}

    async def ingest(self, **kwargs):
        self.ingest_calls.append(kwargs)
        self.documents[kwargs["document_id"]] = {
            "document_id": kwargs["document_id"],
            "document_name": kwargs["document_name"],
            "file_type": kwargs["file_type"],
            "source_uri": kwargs.get("source_uri") or f"local://{kwargs['document_id']}",
            "status": "completed",
            "chunk_count": 2,
            "created_at": "2026-06-03T00:00:00Z",
            "error_message": None,
        }
        return 2

    async def delete(self, document_id: str) -> None:
        self.delete_calls.append(document_id)
        self.documents.pop(document_id, None)

    async def get_document(self, document_id: str):
        payload = self.documents.get(document_id)
        if payload is None:
            return None

        class Doc:
            id = payload["document_id"]
            name = payload["document_name"]
            file_type = payload["file_type"]
            s3_key = payload["source_uri"]
            status = type("Status", (), {"value": payload["status"]})()
            chunk_count = payload["chunk_count"]
            created_at = payload["created_at"]
            error_message = payload["error_message"]

        return Doc()

    async def list_documents(self):
        return [await self.get_document(document_id) for document_id in self.documents]


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
                "correlation_id": "cid-ingest-1",
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert stub.ingest_calls[0]["document_id"] == "doc-1"
    assert stub.ingest_calls[0]["correlation_id"] == "cid-ingest-1"
    assert response.json()["chunk_count"] == 2


def test_delete_ingest_router_deletes_document() -> None:
    stub = StubIngestUseCase()
    app.dependency_overrides[get_ingest_use_case] = lambda: stub

    with TestClient(app) as client:
        response = client.delete("/api/ingest/doc-9")

    app.dependency_overrides.clear()

    assert response.status_code == 204
    assert stub.delete_calls == ["doc-9"]


def test_get_ingest_router_returns_document_status() -> None:
    stub = StubIngestUseCase()
    app.dependency_overrides[get_ingest_use_case] = lambda: stub

    with TestClient(app) as client:
        client.post(
            "/api/ingest",
            json={
                "document_id": "doc-1",
                "document_name": "Guide",
                "file_type": "md",
                "markdown": "# Title\nBody",
            },
        )
        response = client.get("/api/ingest/doc-1")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_list_ingest_router_returns_documents() -> None:
    stub = StubIngestUseCase()
    app.dependency_overrides[get_ingest_use_case] = lambda: stub

    with TestClient(app) as client:
        client.post(
            "/api/ingest",
            json={
                "document_id": "doc-1",
                "document_name": "Guide",
                "file_type": "md",
                "markdown": "# Title\nBody",
            },
        )
        response = client.get("/api/ingest")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 1
