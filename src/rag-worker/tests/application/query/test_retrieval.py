import pytest

from app.application.use_cases.query import RetrievalUseCase
from app.domain.repositories.vector_repository import SearchLineage, SearchResult


class StubEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str] | None, int, str | None]] = []

    async def search(
        self,
        query_text: str,
        top_k=None,
        document_ids=None,
        correlation_id: str | None = None,
    ):
        self.calls.append((query_text, document_ids, top_k, correlation_id))
        return [
            SearchResult(
                correlation_id=correlation_id or "generated",
                unit_id="doc-1::p0::c0",
                document_id="doc-1",
                display_name="Doc 1",
                caption="reset password",
                content="Reset password from settings.",
                heading_path=["Reset password"],
                lineage=SearchLineage(
                    source_uri="local://doc-1",
                    artifact_uri="local://doc-1#artifact",
                ),
                score=0.9,
                rerank_score=0.9,
            )
        ]


@pytest.mark.asyncio
async def test_retrieval_use_case_passes_query_and_filters() -> None:
    engine = StubEngine()
    use_case = RetrievalUseCase(engine)

    results = await use_case.execute(
        "reset mật khẩu",
        document_ids=["doc-1"],
        top_k=3,
        correlation_id="cid-123",
    )

    assert engine.calls == [("reset mật khẩu", ["doc-1"], 3, "cid-123")]
    assert results[0].correlation_id == "cid-123"
