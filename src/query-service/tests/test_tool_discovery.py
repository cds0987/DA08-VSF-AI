"""
Tests for Issue #43 Acceptance #1: dynamic tool discovery.

Verifies that adding a new summary-style tool to MockMCPClient via
register_tool() is sufficient for the full query-service pipeline to
discover, bind, and execute it — with ZERO changes to routing code.

Test coverage:
  1. MockMCPClient.register_tool() — list_tool_specs / list_tools surface the new tool.
  2. LangGraph path — build_langgraph_tools() includes new tool schema; act_node
     dispatches via call_tool() and streams summary.
  3. Legacy path (HTTP, USE_LANGGRAPH=false) — _choose_route passes discovered_tools;
     route_decision accepts generic tool; _handle_generic_tool streams summary.
  4. route_decision unit tests — normalize / coerce with discovered_tools.
  5. Regression — rag_search and hr_query keep bespoke handling unchanged.
"""

import json
import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import HR_USER_ID, parse_sse

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_GENERIC_TOOL_SUMMARY = "Ticket VINSF-42 created: laptop replacement in progress."

_GENERIC_SPEC_DICT = {
    "name": "it_ticket",
    "description": "Create or query an IT support ticket.",
    "input_schema": {
        "type": "object",
        "properties": {
            "request": {"type": "string", "description": "Describe the IT issue"},
        },
        "required": ["request"],
    },
}


def _get_mcp() -> "MockMCPClient":
    from app.interfaces.api.dependencies import get_mcp_client
    return get_mcp_client()  # type: ignore[return-value]


def _get_router() -> "QueryRouter":
    from app.interfaces.api.dependencies import get_tool_decision_client
    return get_tool_decision_client()  # type: ignore[return-value]


def _register_it_ticket() -> None:
    """Register the generic it_ticket tool on the live MockMCPClient."""
    from app.application.ports import ToolSpec
    mcp = _get_mcp()
    mcp.register_tool(
        spec=ToolSpec(**_GENERIC_SPEC_DICT),
        response={"summary": _GENERIC_TOOL_SUMMARY},
    )


# ---------------------------------------------------------------------------
# 1. MockMCPClient.register_tool()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_tool_appears_in_list_tools():
    """list_tools() must include the newly registered tool name."""
    _register_it_ticket()
    mcp = _get_mcp()
    tools = await mcp.list_tools()
    assert "it_ticket" in tools


@pytest.mark.asyncio
async def test_register_tool_appears_in_list_tool_specs():
    """list_tool_specs() must include a ToolSpec for the new tool."""
    _register_it_ticket()
    mcp = _get_mcp()
    specs = await mcp.list_tool_specs()
    names = [s.name for s in specs]
    assert "it_ticket" in names


@pytest.mark.asyncio
async def test_register_tool_preserves_base_tools():
    """rag_search and hr_query must still be present after registration."""
    _register_it_ticket()
    mcp = _get_mcp()
    tools = await mcp.list_tools()
    assert "rag_search" in tools
    assert "hr_query" in tools


@pytest.mark.asyncio
async def test_call_tool_generic_returns_summary():
    """call_tool() for a registered generic tool must return the fixed summary."""
    _register_it_ticket()
    mcp = _get_mcp()
    result = await mcp.call_tool("it_ticket", {"request": "Need new laptop", "user_id": "u1"})
    assert result.get("summary") == _GENERIC_TOOL_SUMMARY


@pytest.mark.asyncio
async def test_call_tool_unknown_returns_error():
    """call_tool() for an unknown (not registered) tool returns an error dict."""
    mcp = _get_mcp()
    result = await mcp.call_tool("nonexistent_tool", {})
    assert "error" in result


@pytest.mark.asyncio
async def test_register_tool_reset_clears():
    """reset() must clear extra tools so they no longer appear in list_tools."""
    _register_it_ticket()
    mcp = _get_mcp()
    mcp.reset()
    tools = await mcp.list_tools()
    assert "it_ticket" not in tools


# ---------------------------------------------------------------------------
# 2. LangGraph path — build_langgraph_tools dynamic discovery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_langgraph_tools_includes_generic():
    """build_langgraph_tools() must expose generic tool schema from mcp-service."""
    from app.application.langgraph_nodes import build_langgraph_tools
    _register_it_ticket()
    mcp = _get_mcp()
    tools = await build_langgraph_tools(
        mcp_client=mcp,
        allowed_doc_ids=frozenset(["doc-1"]),
        user_id="u-test",
    )
    # Find "it_ticket" (may be a dict for generic tools)
    names = [
        (t["name"] if isinstance(t, dict) else t.name)
        for t in tools
    ]
    assert "it_ticket" in names, f"Expected it_ticket in {names}"


@pytest.mark.asyncio
async def test_build_langgraph_tools_rag_still_bespoke():
    """rag_search must remain as a StructuredTool (not a plain dict)."""
    from app.application.langgraph_nodes import build_langgraph_tools
    from langchain_core.tools import BaseTool
    mcp = _get_mcp()
    tools = await build_langgraph_tools(
        mcp_client=mcp,
        allowed_doc_ids=frozenset(["doc-1"]),
        user_id="u-test",
    )
    rag_tool = next((t for t in tools if (
        t.get("name") if isinstance(t, dict) else t.name
    ) == "rag_search"), None)
    assert rag_tool is not None, "rag_search must be present"
    assert isinstance(rag_tool, BaseTool), "rag_search must be a StructuredTool, not a dict"


@pytest.mark.asyncio
async def test_act_node_dispatches_generic_tool():
    """act_node must call call_tool() for an unknown tool and extract summary."""
    import json as _json
    from app.application.langgraph_nodes import act_node
    from app.application.langgraph_state import create_initial_state, AgentPhase
    from langchain_core.messages import AIMessage

    _register_it_ticket()
    mcp = _get_mcp()

    # Build a minimal AgentState with an AIMessage that has a tool_call to it_ticket.
    initial = create_initial_state(
        question="Tôi cần tạo IT ticket cho laptop mới",
        user_id="u-test",
        user_role="employee",
        user_department="IT",
        allowed_doc_ids=["doc-1"],
        session_id="sess-test",
        max_iterations=3,
        recent_messages=[],
        rag_score_threshold=0.45,
    )
    # Inject an AIMessage with a tool_call to it_ticket.
    ai_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "it_ticket",
            "args": {"request": "Need new laptop"},
            "id": "call_it_123",
            "type": "tool_call",
        }],
    )
    state = {**initial, "messages": [ai_msg]}
    result = await act_node(state, mcp_client=mcp)

    # The tool must have been executed and the summary returned.
    assert result.get("phase") is not None
    tool_messages = [m for m in result.get("messages", []) if hasattr(m, "content")]
    assert len(tool_messages) >= 1
    content = tool_messages[0].content
    assert _GENERIC_TOOL_SUMMARY in content, (
        f"Expected summary in tool message content, got: {content!r}"
    )


def _rag_tool_state(question: str = "Quy định nghỉ phép năm là gì?"):
    from app.application.langgraph_state import create_initial_state
    from langchain_core.messages import AIMessage

    initial = create_initial_state(
        question=question,
        user_id="u-test",
        user_role="employee",
        user_department="HR",
        allowed_doc_ids=["doc-1"],
        session_id="sess-test",
        max_iterations=3,
        recent_messages=[],
        rag_score_threshold=0.45,
    )
    ai_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "rag_search",
            "args": {"top_k": 5},
            "id": "call_rag",
            "type": "tool_call",
        }],
    )
    return {**initial, "messages": [ai_msg]}


@pytest.mark.asyncio
async def test_act_node_rag_weak_results_adaptive_fallback():
    """Chunk dưới ngưỡng nhưng qdrant CÓ kết quả -> fallback top-3 cho LLM, KHÔNG hard-stop."""
    from app.application.langgraph_nodes import act_node
    from app.infrastructure.external.mcp_client import SearchResult

    class _WeakRagMCP:
        async def rag_search(self, query, document_ids, top_k=5):
            return [
                SearchResult(
                    chunk_id="chunk-weak",
                    document_id="doc-1",
                    document_name="leave_policy.md",
                    caption="Chính sách nghỉ phép",
                    parent_text="Nhân viên được 12 ngày phép năm.",
                    heading_path=[],
                    score=0.28,  # < ngưỡng 0.70 nhưng vẫn có kết quả
                )
            ]

    state = _rag_tool_state()
    result = await act_node(state, mcp_client=_WeakRagMCP())

    # Fallback: kết quả weak được đưa vào sources, success, KHÔNG shortcut NO_INFO.
    assert result.get("shortcut_outcome") != "NO_INFO"
    assert len(result["sources"]) == 1
    source = result["sources"][0]
    name = source["document_name"] if isinstance(source, dict) else source.document_name
    assert name == "leave_policy.md"
    assert result["tool_results"][0]["success"] is True


@pytest.mark.asyncio
async def test_act_node_rag_no_results_hard_stops_no_info():
    """Chỉ khi qdrant trả RỖNG mới hard-stop NO_INFO (không có gì để fallback)."""
    from app.application.langgraph_edges import route_after_act
    from app.application.langgraph_nodes import act_node
    from app.application.langgraph_state import AgentPhase

    class _EmptyRagMCP:
        async def rag_search(self, query, document_ids, top_k=5):
            return []

    state = _rag_tool_state()
    result = await act_node(state, mcp_client=_EmptyRagMCP())

    assert result["phase"] == AgentPhase.DONE
    assert result["shortcut_outcome"] == "NO_INFO"
    assert result["sources"] == []
    assert result["shortcut_response"]
    assert result["tool_results"][0]["success"] is False
    assert route_after_act({**state, **result}) == "answer"


# ---------------------------------------------------------------------------
# 3. Legacy path — HTTP integration test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_legacy_generic_tool_streams_summary(hr_client: AsyncClient):
    """
    End-to-end: register a new tool, force-route to it, query returns its summary.

    Acceptance #1 proof: the ONLY change is register_tool() on the mock client
    and force_next_decision() on the router — NO routing code touched.
    """
    from app.application.route_decision import RouteDecision
    from app.domain.outcome import Outcome

    _register_it_ticket()

    router = _get_router()
    router.force_next_decision(
        RouteDecision(
            decision="it_ticket",
            tool_arguments={"request": "laptop issue"},
            reason="test force",
            confidence=1.0,
            outcome=Outcome.SUCCESS,
        )
    )

    r = await hr_client.post("/query", json={
        "question": "Tôi cần mở IT ticket",
        "user_id": HR_USER_ID,
    })
    assert r.status_code == 200, r.text
    events = parse_sse(r.text)

    # Must have token events containing the summary
    token_text = "".join(e.get("token", "") for e in events)
    assert _GENERIC_TOOL_SUMMARY in token_text, (
        f"Expected summary in token stream. Got tokens: {token_text!r}"
    )

    # Done event must be SUCCESS
    done = next((e for e in events if e.get("done")), None)
    assert done is not None
    from app.domain.outcome import Outcome
    assert done.get("outcome") == Outcome.SUCCESS.value


# ---------------------------------------------------------------------------
# 4. route_decision unit tests
# ---------------------------------------------------------------------------

def test_normalize_generic_tool_accepted_with_discovered_tools():
    """normalize_route_decision accepts a generic tool when in discovered_tools."""
    from app.application.route_decision import normalize_route_decision, RouteDecision
    from app.domain.outcome import Outcome

    decision = RouteDecision(
        decision="it_ticket",
        tool_arguments={"request": "laptop"},
        reason="test",
        confidence=0.9,
        outcome=Outcome.SUCCESS,
    )
    result = normalize_route_decision(
        decision,
        default_query="help",
        discovered_tools={"rag_search", "hr_query", "it_ticket"},
    )
    assert result.decision == "it_ticket"
    assert result.outcome == Outcome.SUCCESS


def test_normalize_unknown_tool_falls_back_without_discovered_tools():
    """Without discovered_tools, unknown tool falls back to rag_search."""
    from app.application.route_decision import normalize_route_decision, RouteDecision

    decision = RouteDecision(
        decision="it_ticket",
        tool_arguments={},
        reason="test",
        confidence=0.9,
    )
    result = normalize_route_decision(decision, default_query="help")
    assert result.decision == "rag_search"


def test_coerce_generic_tool_from_route_decision():
    """coerce_route_decision wraps a RouteDecision with generic tool correctly."""
    from app.application.route_decision import coerce_route_decision, RouteDecision
    from app.domain.outcome import Outcome

    raw = RouteDecision(
        decision="it_ticket",
        tool_arguments={"request": "laptop"},
        reason="test",
        confidence=1.0,
        outcome=Outcome.SUCCESS,
    )
    result = coerce_route_decision(
        raw,
        default_query="help",
        discovered_tools={"rag_search", "hr_query", "it_ticket"},
    )
    assert result.decision == "it_ticket"
    assert result.outcome == Outcome.SUCCESS


def test_coerce_generic_tool_from_tool_decision():
    """coerce_route_decision with ToolDecision for generic tool accepted."""
    from app.application.route_decision import coerce_route_decision
    from app.application.tool_decision import ToolDecision
    from app.domain.outcome import Outcome

    raw = ToolDecision(tool_name="it_ticket", arguments={"request": "need help"}, reason="test")
    result = coerce_route_decision(
        raw,
        default_query="help",
        discovered_tools={"rag_search", "hr_query", "it_ticket"},
    )
    assert result.decision == "it_ticket"
    assert result.outcome == Outcome.SUCCESS


# ---------------------------------------------------------------------------
# 5. Regression — bespoke tools unchanged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rag_query_still_works_after_registration(hr_client: AsyncClient):
    """Existing rag_search flow is unaffected by registering a new generic tool."""
    _register_it_ticket()

    r = await hr_client.post("/query", json={
        "question": "Chính sách nghỉ phép là gì?",
        "user_id": HR_USER_ID,
    })
    assert r.status_code == 200
    events = parse_sse(r.text)
    done = next((e for e in events if e.get("done")), None)
    assert done is not None, "Stream must end with done event"


@pytest.mark.asyncio
async def test_hr_query_still_works_after_registration(hr_client: AsyncClient):
    """Existing hr_query flow is unaffected by registering a new generic tool."""
    from app.application.route_decision import RouteDecision

    _register_it_ticket()

    router = _get_router()
    router.force_next_decision(
        RouteDecision(
            decision="hr_query",
            tool_arguments={"intent": "leave_balance"},
            reason="test force hr",
            confidence=1.0,
        )
    )
    r = await hr_client.post("/query", json={
        "question": "Tôi còn bao nhiêu ngày nghỉ?",
        "user_id": HR_USER_ID,
    })
    assert r.status_code == 200
    events = parse_sse(r.text)
    done = next((e for e in events if e.get("done")), None)
    assert done is not None
