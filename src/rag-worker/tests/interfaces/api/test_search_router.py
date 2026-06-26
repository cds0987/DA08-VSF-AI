"""POST /api/search — schema request/response + DI override.

Stub SearchUseCase trực tiếp (giống test_ingest_router) để chốt HTTP contract:
  - body {query, document_ids, top_k} -> truyền đúng vào use-case.
  - response {candidates:[...]} map đúng field theo schema.
  - top_k mặc định 20; document_ids None hợp lệ (ACL fail-closed nằm ở tầng store).
"""

from fastapi.testclient import TestClient

from app.application.use_cases.search import SearchCandidate
from app.interfaces.api.dependencies import get_search_use_case
from app.interfaces.api.main import app


class StubSearchUseCase:
    def __init__(self, candidates=None) -> None:
        self.candidates = candidates or []
        self.calls = []

    async def search(self, *, query, document_ids, top_k=20):
        self.calls.append({"query": query, "document_ids": document_ids, "top_k": top_k})
        return self.candidates


def _candidate() -> SearchCandidate:
    return SearchCandidate(
        chunk_id="c1",
        document_id="d1",
        document_name="Doc",
        caption="cap",
        child_text="child",
        parent_text="parent",
        heading_path=["H1"],
        score=0.42,
        page_number=2,
        source_gcs_uri="gs://s",
        markdown_gcs_uri="gs://m",
    )


def test_search_router_returns_mapped_candidates() -> None:
    stub = StubSearchUseCase([_candidate()])
    app.dependency_overrides[get_search_use_case] = lambda: stub

    with TestClient(app) as client:
        response = client.post(
            "/api/search",
            json={"query": "câu hỏi", "document_ids": ["d1"], "top_k": 5},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) == 1
    candidate = body["candidates"][0]
    assert candidate["chunk_id"] == "c1"
    assert candidate["caption"] == "cap"
    assert candidate["source_gcs_uri"] == "gs://s"
    assert candidate["markdown_gcs_uri"] == "gs://m"
    assert candidate["heading_path"] == ["H1"]
    assert candidate["page_number"] == 2
    assert stub.calls == [{"query": "câu hỏi", "document_ids": ["d1"], "top_k": 5}]


def test_search_router_defaults_top_k_and_allows_null_document_ids() -> None:
    stub = StubSearchUseCase([])
    app.dependency_overrides[get_search_use_case] = lambda: stub

    with TestClient(app) as client:
        response = client.post("/api/search", json={"query": "q"})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"candidates": []}
    assert stub.calls == [{"query": "q", "document_ids": None, "top_k": 20}]


def test_search_router_503_when_use_case_unconfigured() -> None:
    # Không override + app.state chưa có search_use_case (TestClient lifespan dựng runtime
    # offline; nếu bootstrap đặt được use-case thì 200, nếu không thì 503). Ở đây chỉ chốt
    # rằng thiếu cấu hình -> 503 qua dependency, bằng cách ép state về None.
    with TestClient(app) as client:
        app.state.search_use_case = None
        response = client.post("/api/search", json={"query": "q"})

    assert response.status_code == 503
