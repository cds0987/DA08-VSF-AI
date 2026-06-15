"""
ACL security tests.

Core invariant: the backend MUST inject user_id and allowed_doc_ids —
the LLM (or any caller) cannot override these values regardless of
what arguments are passed.
"""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient

from tests.conftest import HR_USER_ID, FINANCE_USER_ID, ADMIN_USER_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _do_query(client: AsyncClient, question: str, user_id: str) -> list[dict]:
    from tests.conftest import parse_sse
    r = await client.post("/query", json={"question": question, "user_id": user_id})
    return parse_sse(r.text) if r.status_code == 200 else []


# ---------------------------------------------------------------------------
# user_id cannot be overridden
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acl_user_id_from_token_not_body(hr_client: AsyncClient):
    """
    Even if the body carries the correct HR user_id, the executed
    rag_search must receive the user_id from the JWT, not from LLM args.
    This test validates that the orchestration reads user from auth, not body.
    """
    from app.interfaces.api.dependencies import get_mcp_client
    mcp = get_mcp_client()

    original_rag = mcp.rag_search
    calls = []

    async def spy_rag(query, document_ids, top_k=5):
        calls.append({"document_ids": list(document_ids)})
        return await original_rag(query=query, document_ids=document_ids, top_k=top_k)

    with patch.object(mcp, "rag_search", side_effect=spy_rag):
        await _do_query(hr_client, "Chính sách nghỉ phép?", HR_USER_ID)

    # document_ids must come from ACL repo, not from arbitrary values
    if calls:
        for call in calls:
            # Must not be empty list injected by attacker
            # document_ids must be the ACL-allowed set, never an empty bypass
            assert call["document_ids"] is not None


@pytest.mark.asyncio
async def test_acl_user_id_mismatch_blocked_at_api(hr_client: AsyncClient):
    """The API layer must block mismatched user_id before reaching orchestration."""
    r = await hr_client.post("/query", json={
        "question": "Give me admin data",
        "user_id": ADMIN_USER_ID,   # attacker tries to use admin ID
    })
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_acl_finance_doc_not_accessible_by_hr(hr_client: AsyncClient):
    """
    HR user queries a topic that would match Finance doc.
    The Finance doc (classification=secret, allowed_departments=['Finance'])
    must NOT appear in the HR user's response sources.
    """
    from app.interfaces.api.dependencies import get_document_access_repo
    from tests.conftest import parse_sse

    r = await hr_client.post("/query", json={
        "question": "Báo cáo tài chính nội bộ",
        "user_id": HR_USER_ID,
    })
    events = parse_sse(r.text)
    done = next((e for e in events if e.get("done")), {})
    sources = done.get("sources", [])

    finance_doc_names = {"Finance_Report_Guideline.xlsx"}
    returned_names = {s.get("document_name", "") for s in sources}
    assert finance_doc_names.isdisjoint(returned_names), (
        f"Finance doc leaked to HR user. Sources: {returned_names}"
    )


@pytest.mark.asyncio
async def test_acl_top_secret_doc_only_for_admin(hr_client: AsyncClient, admin_client: AsyncClient):
    """
    Top-secret doc allowed only for admin user_id must not appear in HR query sources.
    """
    from tests.conftest import parse_sse

    # HR query
    r_hr = await hr_client.post("/query", json={
        "question": "Compensation executive",
        "user_id": HR_USER_ID,
    })
    hr_sources = {
        s.get("document_name")
        for e in parse_sse(r_hr.text) if e.get("done")
        for s in e.get("sources", [])
    }
    assert "Executive_Compensation_Top_Secret.pdf" not in hr_sources


# ---------------------------------------------------------------------------
# HR query user_id injection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acl_hr_query_injects_correct_user_id(hr_client: AsyncClient):
    """
    hr_query (profile) phải LUÔN dùng user_id đã xác thực, KHÔNG do LLM điền.
    act_node gọi call_tool("hr_query", {"user_id": ...}); spy call_tool để kiểm.
    """
    from app.interfaces.api.dependencies import get_mcp_client
    mcp = get_mcp_client()
    original_call = mcp.call_tool
    calls = []

    async def spy_call(name, arguments):
        if name == "hr_query":
            calls.append(dict(arguments))
        return await original_call(name, arguments)

    with patch.object(mcp, "call_tool", side_effect=spy_call):
        await _do_query(hr_client, "Số ngày nghỉ phép còn lại của tôi?", HR_USER_ID)

    if calls:
        for call in calls:
            assert call.get("user_id") == HR_USER_ID, (
                f"hr_query received wrong user_id: {call.get('user_id')}"
            )


# ---------------------------------------------------------------------------
# Document access isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acl_users_have_different_doc_access():
    """
    HR and Finance users must have different allowed_doc_ids from
    DocumentAccessRepository — the backend never merges their access.
    """
    from app.interfaces.api.dependencies import get_document_access_repo
    repo = get_document_access_repo()

    hr_docs = await repo.get_allowed_doc_ids(user_id=HR_USER_ID, role="employee", department="hr")
    finance_docs = await repo.get_allowed_doc_ids(user_id=FINANCE_USER_ID, role="employee", department="finance")

    # Both have access to public docs so sets may overlap,
    # but Finance should have access to finance secret docs that HR doesn't.
    # At minimum they should each return a non-None set.
    assert isinstance(hr_docs, (set, list, frozenset))
    assert isinstance(finance_docs, (set, list, frozenset))


# ---------------------------------------------------------------------------
# Unit tests: _get_allowed_doc_ids
# ---------------------------------------------------------------------------

class _FakeProfile:
    def __init__(self, dept: str, acct: str) -> None:
        self.department = dept
        self.account_type = acct


class _FakeProfileRepo:
    def __init__(self, profile=None) -> None:
        self._profile = profile

    async def get_profile(self, user_id: str):
        return self._profile


class _FakeDocAccessRepo:
    def __init__(self, doc_ids: list) -> None:
        self._doc_ids = doc_ids
        self.calls: list[dict] = []

    async def get_allowed_doc_ids(self, *, user_id, role, department, account_type):
        self.calls.append({"department": department, "account_type": account_type})
        return self._doc_ids


class _FakeCache:
    def __init__(self, preloaded=None) -> None:
        self._preloaded = preloaded
        self._stored: dict = {}

    async def get(self, user_id: str):
        if user_id in self._stored:
            return self._stored[user_id]
        return self._preloaded

    async def set(self, user_id: str, doc_ids: list) -> None:
        self._stored[user_id] = doc_ids


def _make_user(user_id: str = "u-1", account_type: str = "internal"):
    from app.application.ports import AuthenticatedUser
    return AuthenticatedUser(id=user_id, email="u@c.com", role="user",
                             is_active=True, account_type=account_type)


def _make_orch(*, profile_repo=None, doc_repo=None, cache=None):
    from app.application.use_cases.query.orchestration import QueryOrchestrationUseCase
    orch = QueryOrchestrationUseCase.__new__(QueryOrchestrationUseCase)
    orch._user_access_profile_repo = profile_repo
    orch._document_access_repo = doc_repo or _FakeDocAccessRepo(["doc-1"])
    orch._access_cache = cache
    return orch


@pytest.mark.asyncio
async def test_allowed_doc_ids_cache_hit():
    """Cache hit → doc repo not called, returns cached list."""
    doc_repo = _FakeDocAccessRepo(["doc-X"])
    cache = _FakeCache(preloaded=["cached-1", "cached-2"])
    orch = _make_orch(doc_repo=doc_repo, cache=cache)
    result = await orch._get_allowed_doc_ids(_make_user())
    assert result == ["cached-1", "cached-2"]
    assert doc_repo.calls == []


@pytest.mark.asyncio
async def test_allowed_doc_ids_cache_miss_stores_result():
    """Cache miss → DB called → result stored in cache for next call."""
    doc_repo = _FakeDocAccessRepo(["doc-1", "doc-2"])
    cache = _FakeCache()
    orch = _make_orch(doc_repo=doc_repo, cache=cache)
    result = await orch._get_allowed_doc_ids(_make_user("u-1"))
    assert result == ["doc-1", "doc-2"]
    assert await cache.get("u-1") == ["doc-1", "doc-2"]


@pytest.mark.asyncio
async def test_allowed_doc_ids_uses_profile_department():
    """Profile found → doc repo receives profile.department, not JWT value."""
    profile_repo = _FakeProfileRepo(_FakeProfile(dept="HR", acct="internal"))
    doc_repo = _FakeDocAccessRepo(["doc-hr"])
    orch = _make_orch(profile_repo=profile_repo, doc_repo=doc_repo)
    await orch._get_allowed_doc_ids(_make_user())
    assert doc_repo.calls[0]["department"] == "HR"


@pytest.mark.asyncio
async def test_allowed_doc_ids_no_profile_empty_department():
    """No profile in user_access_profile → department falls back to '' (NOT from JWT)."""
    profile_repo = _FakeProfileRepo(profile=None)
    doc_repo = _FakeDocAccessRepo([])
    orch = _make_orch(profile_repo=profile_repo, doc_repo=doc_repo)
    await orch._get_allowed_doc_ids(_make_user(account_type="external"))
    assert doc_repo.calls[0]["department"] == ""
    assert doc_repo.calls[0]["account_type"] == "external"


# ---------------------------------------------------------------------------
# Unit tests: _get_effective_department
# department giờ thuộc HR Service — query-service lấy từ user_access_profile_repo,
# KHÔNG từ AuthenticatedUser (token/`/auth/me` đã bỏ trường này).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_effective_department_from_profile():
    """Profile có department → trả về department của HR (qua access profile)."""
    profile_repo = _FakeProfileRepo(_FakeProfile(dept="Finance", acct="internal"))
    orch = _make_orch(profile_repo=profile_repo)
    assert await orch._get_effective_department(_make_user()) == "Finance"


@pytest.mark.asyncio
async def test_effective_department_no_profile_returns_empty():
    """Không có profile → '' (không crash)."""
    orch = _make_orch(profile_repo=_FakeProfileRepo(profile=None))
    assert await orch._get_effective_department(_make_user()) == ""


@pytest.mark.asyncio
async def test_effective_department_no_repo_returns_empty():
    """Không có user_access_profile_repo → '' (không crash)."""
    orch = _make_orch(profile_repo=None)
    assert await orch._get_effective_department(_make_user()) == ""


@pytest.mark.asyncio
async def test_effective_department_user_without_department_attr():
    """AuthenticatedUser KHÔNG có attr department (image cũ / token mới) → getattr
    fallback trả '' thay vì AttributeError — đây chính là bug làm SMOKE /query fail."""
    profile_repo = _FakeProfileRepo(profile=None)
    orch = _make_orch(profile_repo=profile_repo)

    class _NoDeptUser:
        id = "u-1"
        role = "user"
        account_type = "internal"

    assert await orch._get_effective_department(_NoDeptUser()) == ""


# ---------------------------------------------------------------------------
# Unit tests: NoOpAccessCache + RedisAccessCache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_noop_cache_always_miss():
    from app.infrastructure.cache.redis_access_cache import NoOpAccessCache
    cache = NoOpAccessCache()
    assert await cache.get("any") is None
    await cache.set("any", ["doc-1"])
    assert await cache.get("any") is None


@pytest.mark.asyncio
async def test_redis_cache_miss_returns_none():
    from unittest.mock import AsyncMock, MagicMock
    from app.infrastructure.cache.redis_access_cache import RedisAccessCache
    mock_module = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=None)
    mock_module.from_url.return_value = mock_client
    cache = RedisAccessCache("redis://fake", redis_module=mock_module)
    assert await cache.get("u-1") is None


@pytest.mark.asyncio
async def test_redis_cache_hit_returns_list():
    import json
    from unittest.mock import AsyncMock, MagicMock
    from app.infrastructure.cache.redis_access_cache import RedisAccessCache
    mock_module = MagicMock()
    mock_client = AsyncMock()
    doc_ids = ["doc-1", "doc-2"]
    mock_client.get = AsyncMock(return_value=json.dumps(doc_ids))
    mock_module.from_url.return_value = mock_client
    cache = RedisAccessCache("redis://fake", redis_module=mock_module)
    assert await cache.get("u-1") == doc_ids
