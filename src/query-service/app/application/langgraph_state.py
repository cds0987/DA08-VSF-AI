from typing import Annotated, TypedDict
from langgraph.graph import add_messages
from enum import Enum


class AgentPhase(str, Enum):
    PLANNING = "planning"   # plan_node: choosing tool steps (maps to "thinking" in SSE)
    THINKING = "thinking"   # think_node: checking sufficiency
    ACTING = "acting"       # act_node: executing a tool step
    OBSERVING = "observing" # observe_node: recording results
    GENERATING = "generating"
    DONE = "done"


class ToolCallResult(TypedDict):
    tool_name: str
    success: bool
    data: str
    error: str | None


class SourceDoc(TypedDict):
    document_name: str
    caption: str
    heading_path: list[str]
    score: float
    source_gcs_uri: str
    document_id: str
    page_number: int | None


class AgentState(TypedDict):
    """
    LangGraph state for the VinSmartFuture ReAct agent.

    Key design decisions:
    - `messages` is the canonical conversation history (LangGraph manages it via add_messages)
    - `iteration` replaces remaining_steps for explicit control and SSE reporting
    - `phase` tracks the current ReAct stage for streaming events
    - `shortcut_response` / `tool_results` / `sources` are scratch-pad fields
    - `user_id`, `allowed_doc_ids` are injected at entry and never modified by LLM
    """

    # --- Conversation (managed by LangGraph add_messages) ---
    messages: Annotated[list, add_messages]

    # --- Loop control ---
    iteration: int
    max_iterations: int

    # --- Phase tracking (for SSE streaming) ---
    phase: AgentPhase
    previous_phase: AgentPhase

    # --- Plan-and-Execute scratch pad ---
    shortcut_response: str | None
    shortcut_outcome: str | None
    tool_results: list[ToolCallResult]
    sources: list[SourceDoc]
    # Plan-and-Execute plan state
    tool_plan: list[dict]    # serialized PlanStep list (ordered tool steps)
    plan_cursor: int         # index of the next step to execute in tool_plan
    replan_count: int        # number of times plan_node has been invoked for a replan
    sufficiency: dict | None # last Sufficiency verdict from think_node

    # --- ACL context (injected at entry, never modified by LLM) ---
    user_id: str
    user_role: str
    user_department: str
    allowed_doc_ids: list[str]
    # Ngưỡng điểm RAG (config-driven) để act_node lọc kết quả — trước hardcode 0.70.
    rag_score_threshold: float
    # Số chunk tối đa lấy từ rag-service mỗi lần gọi (config-driven).
    rag_top_k: int

    # --- Observability accumulator ---
    # rag_search_events: list of JSON-safe dicts written by act_node per rag_search call.
    # Each entry: {query, top_k, allowed_count, threshold, total, qualified, scores, doc_names,
    #              start (ISO), end (ISO)}.  Consumed by orchestration to build Langfuse spans.
    rag_search_events: list

    # --- Metadata ---
    session_id: str
    question: str


def create_initial_state(
    question: str,
    user_id: str,
    user_role: str,
    user_department: str,
    allowed_doc_ids: list[str],
    session_id: str,
    max_iterations: int = 3,
    recent_messages: list | None = None,
    rag_score_threshold: float = 0.70,
    rag_top_k: int = 5,
) -> AgentState:
    """
    recent_messages: optional list of LangChain BaseMessage objects representing
    the last N turns of conversation history. Passed as the initial `messages` list
    so the triage and think nodes have context for follow-up queries.
    """
    return AgentState(
        messages=recent_messages or [],
        iteration=0,
        max_iterations=max_iterations,
        phase=AgentPhase.PLANNING,
        previous_phase=AgentPhase.PLANNING,
        shortcut_response=None,
        shortcut_outcome=None,
        tool_results=[],
        sources=[],
        tool_plan=[],
        plan_cursor=0,
        replan_count=0,
        sufficiency=None,
        rag_search_events=[],
        user_id=user_id,
        user_role=user_role,
        user_department=user_department,
        allowed_doc_ids=allowed_doc_ids,
        rag_score_threshold=rag_score_threshold,
        rag_top_k=rag_top_k,
        session_id=session_id,
        question=question,
    )
