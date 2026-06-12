"""
Pydantic schemas for Plan-and-Execute agent architecture.

Used with OpenAIResponsesChatModel.with_structured_output() to get genuinely
typed structured output from the Responses API (text.format / json_schema).

Three schemas:
  ToolPlan    — produced by plan_node: ordered list of tool steps to execute.
  Sufficiency — produced by think_node: judgment on whether gathered context
                is sufficient to answer the user's question.
"""

from typing import Literal

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """One tool call step in the execution plan."""

    tool: Literal["rag_search", "hr_query"] = Field(
        description="Tool to call: rag_search (documents/policies) or hr_query (personal HR data)."
    )
    query: str | None = Field(
        default=None,
        description="Search query for rag_search (leave None to use user's raw question).",
    )
    intent: Literal["leave_balance", "leave_requests", "payroll"] | None = Field(
        default=None,
        description="HR intent for hr_query: leave_balance | leave_requests | payroll.",
    )
    reason: str = Field(
        description="Brief reason why this tool step is needed.",
    )


class ToolPlan(BaseModel):
    """
    Ordered execution plan produced by plan_node.

    direct_answer=True means no tool call is needed (e.g. a greeting slipped through
    triage, or a meta question that can be answered from conversation history).
    """

    direct_answer: bool = Field(
        default=False,
        description="True if the question can be answered directly without any tool call.",
    )
    steps: list[PlanStep] = Field(
        default_factory=list,
        description="Ordered list of tool steps to execute. Empty when direct_answer=True.",
    )


class Sufficiency(BaseModel):
    """
    Sufficiency verdict produced by think_node after all plan steps have been executed.

    If enough=False and replan is allowed (replan_count < 1), plan_node will be
    called again with the refine_query hint to produce a revised plan.
    """

    enough: bool = Field(
        description="True if the retrieved context is sufficient to answer the user's question.",
    )
    reason: str = Field(
        description="Short explanation of the verdict.",
    )
    refine_query: str | None = Field(
        default=None,
        description="Suggested refined search query for replan (only when enough=False).",
    )
