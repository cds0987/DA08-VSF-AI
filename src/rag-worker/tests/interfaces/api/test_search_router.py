from fastapi.testclient import TestClient

from app.application.use_cases.query import RetrievalUseCase
from app.domain.repositories.vector_repository import SearchLineage, SearchResult
from app.interfaces.api.dependencies import get_retrieval_use_case
from app.interfaces.api.main import app


class StubRetrievalUseCase(RetrievalUseCase):
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str] | None, int, str | None]] = []

    async def execute(
        self,
        query_text: str,
        *,
        document_ids: list[str] | None = None,
        top_k: int = 5,
        correlation_id: str | None = None,
    ):
        self.calls.append((query_text, document_ids, top_k, correlation_id))
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
            json={
                "query_text": "reset mật khẩu",
                "document_ids": ["doc-1"],
                "top_k": 3,
                "correlation_id": "cid-abc",
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert stub.calls == [("reset mật khẩu", ["doc-1"], 3, "cid-abc")]
    result = body["results"][0]
    assert result["chunk_id"] == "doc-1::p0::c0"
    assert result["document_name"] == "Account Guide"
    assert result["parent_text"] == "Vào Cài đặt > Bảo mật để đặt lại mật khẩu."
    assert result["source_s3_uri"] == "local://doc-1"
    assert result["markdown_s3_uri"] == "local://doc-1#artifact"
    assert result["page_number"] == 1
