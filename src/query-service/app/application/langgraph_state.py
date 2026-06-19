from typing import Annotated, TypedDict
from langgraph.graph import add_messages
from enum import Enum


class AgentPhase(str, Enum):
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
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
    ref: int        # citation ref number [N], 1-indexed global per turn
    chunk_id: str   # for deduplication across multi-call iterations


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

    # --- ReAct scratch pad ---
    shortcut_response: str | None
    shortcut_outcome: str | None
    tool_results: list[ToolCallResult]
    sources: list[SourceDoc]

    # --- ACL context (injected at entry, never modified by LLM) ---
    user_id: str
    user_role: str
    user_department: str
    allowed_doc_ids: list[str]
    # Số chunk tối đa lấy từ rag-service mỗi lần gọi (config-driven).
    rag_top_k: int
    # Cosine score threshold — backup khi LlmReranker fail → NoopReranker trả cosine scores.
    rag_score_threshold: float

    # --- Loop termination guards ---
    # force_answer: set True by observe_node (iteration cap) or act_node (duplicate tool call)
    # to tell think_node to produce a final text answer without calling any tool.
    force_answer: bool
    # tool_call_signatures: tracks (tool_name, args) pairs already executed so
    # act_node can detect duplicate calls and set force_answer before the loop repeats.
    tool_call_signatures: list[str]

    # --- Citation ref counter ---
    # Incremented by act_node each rag_search call so each chunk gets a globally unique [N].
    source_ref_counter: int

    # --- Observability accumulator ---
    # rag_search_events: list of JSON-safe dicts written by act_node per rag_search call.
    # Each entry: {query, top_k, allowed_count, total, qualified, scores, doc_names,
    #              start (ISO), end (ISO)}.  Consumed by orchestration to build Langfuse spans.
    rag_search_events: list

    # --- Triage decision (cho UI minh bạch "model nghĩ gì") ---
    # route + reason do triage_node trả; orchestration phát ra SSE thought event.
    triage_route: str
    triage_reason: str

    # --- Verify decision (sufficiency gate "think 2", agent_verify_sufficiency) ---
    # verify_node trả: "sufficient" -> answer(synthesis); "insufficient" -> think (tra thêm).
    # verify_missing/refined: gợi ý cho think khi cần tra cứu thêm.
    verify_decision: str
    verify_reason: str

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
    rag_top_k: int = 5,
    rag_score_threshold: float = 0.45,
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
        phase=AgentPhase.THINKING,
        previous_phase=AgentPhase.THINKING,
        shortcut_response=None,
        shortcut_outcome=None,
        tool_results=[],
        sources=[],
        force_answer=False,
        tool_call_signatures=[],
        rag_search_events=[],
        user_id=user_id,
        user_role=user_role,
        user_department=user_department,
        allowed_doc_ids=allowed_doc_ids,
        rag_top_k=rag_top_k,
        rag_score_threshold=rag_score_threshold,
        source_ref_counter=0,
        triage_route="",
        triage_reason="",
        verify_decision="",
        verify_reason="",
        session_id=session_id,
        question=question,
    )
