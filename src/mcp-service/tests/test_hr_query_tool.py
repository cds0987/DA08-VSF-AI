from __future__ import annotations

import asyncio

import pytest

from app.core.config import McpSettings
from app.tools.hr_query import HrQueryTool


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


def _settings() -> McpSettings:
    return McpSettings(
        host="0.0.0.0",
        port=8003,
        log_level="INFO",
        app_env="development",
        internal_token="",
        provider="qdrant",
        collection="rag_chatbot",
        embed_model="offline",
        dimension=256,
        url="",
        api_key="",
        embed_base_url="",
        embed_api_key="",
        rerank_impl="none",
        rerank_model="gpt-4o-mini",
        rerank_base_url="",
        rerank_api_key="",
        rerank_timeout_seconds=30.0,
        rerank_batch_size=8,
        rerank_passage_chars=800,
        top_k_candidates=20,
        rerank_top_k=3,
        rerank_threshold=0.6,
        options={},
    )


def test_hr_query_tool_returns_expected_shapes() -> None:
    tool = HrQueryTool(_settings(), {"params": {"database_url": "sqlite:///ignored.db"}})
    mcp = FakeMCP()
    tool.register(mcp)

    leave_balance = asyncio.run(mcp.tools["hr_query"]("11111111-1111-4111-8111-111111111111", "leave_balance"))
    leave_requests = asyncio.run(mcp.tools["hr_query"]("11111111-1111-4111-8111-111111111111", "leave_requests"))
    attendance = asyncio.run(mcp.tools["hr_query"]("11111111-1111-4111-8111-111111111111", "attendance"))
    onboarding = asyncio.run(mcp.tools["hr_query"]("11111111-1111-4111-8111-111111111111", "onboarding"))

    assert leave_balance == {
        "intent": "leave_balance",
        "data": {"annual_remaining": 8, "sick_remaining": 9},
        "leave_balance": {"annual_remaining": 8, "sick_remaining": 9},
        "summary": "Ban con 8 ngay phep nam va 9 ngay phep om.",
    }
    assert leave_requests["intent"] == "leave_requests"
    assert leave_requests["data"] == leave_requests["leave_requests"]
    assert leave_requests["leave_requests"]["requests"][0]["status"] == "approved"
    assert attendance["attendance"] == {"work_days": 20, "late_count": 1, "absent_count": 0}
    assert onboarding["onboarding"]["status"] == "completed"


def test_hr_query_tool_rejects_unknown_user_id() -> None:
    tool = HrQueryTool(_settings(), {})
    mcp = FakeMCP()
    tool.register(mcp)

    with pytest.raises(ValueError, match="no HR data available"):
        asyncio.run(mcp.tools["hr_query"]("33333333-3333-4333-8333-333333333333", "leave_balance"))
