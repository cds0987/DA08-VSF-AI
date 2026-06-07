from fastapi.testclient import TestClient

from app.interfaces.api.dependencies import get_ingest_use_case
from app.interfaces.api.main import app


# Tạo ingest đã chuyển sang NATS (doc.ingest) — không còn POST /ingest.
# Router chỉ còn ĐỌC/quản lý: GET document, GET job, list, DELETE. Test seed stub trực tiếp.


class StubIngestUseCase:
    def __init__(self) -> None:
        self.delete_calls = []
        self.documents = {}
        self.jobs = {}

    def seed_document(self, document_id: str = "doc-1") -> None:
        self.documents[document_id] = {
            "document_id": document_id,
            "document_name": "Guide",
            "file_type": "md",
            "source_uri": f"local://{document_id}",
            "status": "queued",
            "chunk_count": 0,
            "created_at": "2026-06-03T00:00:00Z",
            "error_message": None,
        }

    def seed_job(self, job_id: str = "job-1", document_id: str = "doc-1"):
        job = type(
            "Job",
            (),
            {
                "id": job_id,
                "document_id": document_id,
                "status": "pending",
                "claim_id": None,
                "attempt": 0,
                "chunk_count": 0,
                "error_message": None,
                "created_at": "2026-06-03T00:00:00Z",
                "updated_at": "2026-06-03T00:00:00Z",
            },
        )()
        self.jobs[job_id] = job
        return job

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

    async def get_job(self, job_id: str):
        return self.jobs.get(job_id)

    async def list_documents(self):
        return [await self.get_document(document_id) for document_id in self.documents]


def test_delete_ingest_router_deletes_document() -> None:
    stub = StubIngestUseCase()
    app.dependency_overrides[get_ingest_use_case] = lambda: stub

    with TestClient(app) as client:
        response = client.delete("/api/ingest/doc-9")

    app.dependency_overrides.clear()

    assert response.status_code == 204
    assert stub.delete_calls == ["doc-9"]


def test_delete_ingest_router_requires_api_key_when_configured(monkeypatch) -> None:
    stub = StubIngestUseCase()
    app.dependency_overrides[get_ingest_use_case] = lambda: stub
    monkeypatch.setenv("INGEST_DELETE_API_KEY", "secret")

    with TestClient(app) as client:
        unauthorized = client.delete("/api/ingest/doc-9")
        authorized = client.delete("/api/ingest/doc-9", headers={"X-API-Key": "secret"})

    app.dependency_overrides.clear()
    monkeypatch.delenv("INGEST_DELETE_API_KEY", raising=False)

    assert unauthorized.status_code == 401
    assert authorized.status_code == 204


def test_get_ingest_router_returns_document_status() -> None:
    stub = StubIngestUseCase()
    stub.seed_document("doc-1")
    app.dependency_overrides[get_ingest_use_case] = lambda: stub

    with TestClient(app) as client:
        response = client.get("/api/ingest/doc-1")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_list_ingest_router_returns_documents() -> None:
    stub = StubIngestUseCase()
    stub.seed_document("doc-1")
    app.dependency_overrides[get_ingest_use_case] = lambda: stub

    with TestClient(app) as client:
        response = client.get("/api/ingest")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_ingest_job_router_returns_job_status() -> None:
    stub = StubIngestUseCase()
    stub.seed_job("job-1", "doc-1")
    app.dependency_overrides[get_ingest_use_case] = lambda: stub

    with TestClient(app) as client:
        response = client.get("/api/ingest/jobs/job-1")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-1"
    assert response.json()["status"] == "pending"
