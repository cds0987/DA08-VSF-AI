from fastapi.testclient import TestClient

from app.application.use_cases.query import RetrievalUseCase
from app.domain.repositories.vector_repository import SearchLineage, SearchResult
from app.interfaces.api.dependencies import get_retrieval_use_case
from app.interfaces.api.main import app


class StubRetrievalUseCase(RetrievalUseCase):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def execute(self, question: str, *, correlation_id: str | None = None):
        self.calls.append((question, correlation_id))
        return [
            SearchResult(
                correlation_id=correlation_id or "generated",
                unit_id="doc-1::p0::c0",
                document_id="doc-1",
                display_name="Account Guide",
                caption="reset mật khẩu",
                content="Vào Cài đặt > Bảo mật để đặt lại mật khẩu.",
                heading_path=["Reset mật khẩu"],
                lineage=SearchLineage(
                    source_uri="local://doc-1",
                    artifact_uri="local://doc-1#artifact",
                ),
                page_number=1,
                score=0.91,
                rerank_score=0.87,
            )
        ]


def test_search_router_returns_contract_payload() -> None:
    stub = StubRetrievalUseCase()
    app.dependency_overrides[get_retrieval_use_case] = lambda: stub

    with TestClient(app) as client:
        response = client.post(
            "/api/search",
            json={"question": "reset mật khẩu", "correlation_id": "cid-abc"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert stub.calls == [("reset mật khẩu", "cid-abc")]
    assert body["results"][0]["correlation_id"] == "cid-abc"
    assert body["results"][0]["unit_id"] == "doc-1::p0::c0"
    assert body["results"][0]["lineage"]["source_uri"] == "local://doc-1"
