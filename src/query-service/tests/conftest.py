"""
Shared fixtures for query-service tests.

All tests run against an in-process ASGI transport (no real server required).
Settings are forced to safe mock mode via env-var overrides so tests never
touch real databases, OpenAI, NATS, or Redis.
"""

import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Force mock mode for every setting BEFORE the app module is imported.
os.environ.setdefault("AUTH_MODE", "mock")
os.environ.setdefault("MCP_MODE", "mock")
os.environ.setdefault("NATS_MODE", "mock")
os.environ.setdefault("LLM_MODE", "mock")
os.environ.setdefault("RATE_LIMITER_MODE", "memory")
# USE_LANGGRAPH=false in tests: LangGraph needs a real OpenAI key; mock mode uses legacy orchestration.
os.environ.setdefault("USE_LANGGRAPH", "false")
os.environ.setdefault("ENABLE_DEV_ENDPOINTS", "true")
os.environ.setdefault("APP_ENV", "development")


from app.interfaces.api.main import app  # noqa: E402 — must come after env setup
from app.interfaces.api.dependencies import reset_state_for_tests  # noqa: E402
from app.infrastructure.config import get_settings  # noqa: E402


# ---------------------------------------------------------------------------
# Mock tokens (must match auth_service.MOCK_TOKENS)
# ---------------------------------------------------------------------------
HR_TOKEN = "mock-user-hr"
HR_USER_ID = "11111111-1111-4111-8111-111111111111"

FINANCE_TOKEN = "mock-user-finance"
FINANCE_USER_ID = "22222222-2222-4222-8222-222222222222"

ADMIN_TOKEN = "mock-admin"
ADMIN_USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def reset_state():
    """Reset all in-memory state before each test."""
    get_settings.cache_clear()
    reset_state_for_tests()
    yield
    reset_state_for_tests()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    """Async HTTP client talking directly to the ASGI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def hr_client(client: AsyncClient) -> AsyncClient:
    client.headers.update(auth(HR_TOKEN))
    return client


@pytest_asyncio.fixture
async def finance_client(client: AsyncClient) -> AsyncClient:
    client.headers.update(auth(FINANCE_TOKEN))
    return client


@pytest_asyncio.fixture
async def admin_client(client: AsyncClient) -> AsyncClient:
    client.headers.update(auth(ADMIN_TOKEN))
    return client


# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------

def parse_sse(raw: str) -> list[dict]:
    """Parse SSE text/event-stream body into a list of JSON event dicts."""
    import json
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    events.append({"_raw": payload})
    return events
