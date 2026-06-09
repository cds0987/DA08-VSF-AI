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
        user_id=user_id,
        user_role=user_role,
        user_department=user_department,
        allowed_doc_ids=allowed_doc_ids,
        session_id=session_id,
        question=question,
    )
