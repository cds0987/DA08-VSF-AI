import pytest

from app.application.use_cases.query import RetrievalUseCase
from app.domain.repositories.vector_repository import SearchLineage, SearchResult


class StubEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def search(self, question: str, correlation_id: str | None = None):
        self.calls.append((question, correlation_id))
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
async def test_retrieval_use_case_passes_question_and_correlation_id() -> None:
    engine = StubEngine()
    use_case = RetrievalUseCase(engine)

    results = await use_case.execute("reset mật khẩu", correlation_id="cid-123")

    assert engine.calls == [("reset mật khẩu", "cid-123")]
    assert results[0].correlation_id == "cid-123"
