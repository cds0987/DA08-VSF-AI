from pydantic import BaseModel, Field

from app.application.hr_intents import HrIntentLiteral


class RagSearchArgs(BaseModel):
    query: str = Field(description="Search query in Vietnamese or English")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of results")


class HrQueryArgs(BaseModel):
    intent: HrIntentLiteral = Field(
        description="HR data type to query"
    )


TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "name": "rag_search",
        "description": (
            "Search internal company documents, policies, and procedures. "
            "Returns relevant text chunks ranked by relevance score."
        ),
        "parameters": RagSearchArgs.model_json_schema(),
    },
    {
        "type": "function",
        "name": "hr_query",
        "description": (
            "Query the authenticated user's personal HR data: "
            "remaining leave balance, leave request status, or payroll. "
            "NOTE: user_id is automatically injected from authentication."
        ),
        "parameters": HrQueryArgs.model_json_schema(),
    },
]


ACL_WHITELIST = {"rag_search", "hr_query"}
