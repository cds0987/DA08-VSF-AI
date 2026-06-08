from dataclasses import dataclass
import json
import re
from typing import Any
import unicodedata

import httpx

from app.application.ports import ToolSpec
from app.infrastructure.db.mock_data import MOCK_DOCUMENTS, MOCK_HR_DATA
from app.infrastructure.config import Settings

streamable_http_client = None
ClientSession = None

MCP_INTERNAL_TOKEN_HEADER = "X-Internal-Token"


@dataclass(frozen=True)
class ToolCallRecord:
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    document_id: str
    document_name: str
    caption: str
    parent_text: str
    heading_path: list[str]
    score: float
    page_number: int | None = None
    source_gcs_uri: str = ""
    markdown_gcs_uri: str = ""


@dataclass(frozen=True)
class LeaveBalanceDTO:
    annual_total: int
    annual_used: int
    annual_remaining: int
    sick_total: int
    sick_used: int
    sick_remaining: int


@dataclass(frozen=True)
class LeaveRequestDTO:
    leave_type: str
    start_date: str
    end_date: str
    days_count: int
    status: str


@dataclass(frozen=True)
class PayrollDTO:
    period: str
    gross_salary: float
    deductions: float
    net_salary: float


@dataclass(frozen=True)
class HrQueryResult:
    intent: str
    leave_balance: LeaveBalanceDTO | None = None
    leave_requests: list[LeaveRequestDTO] | None = None
    payroll: list[PayrollDTO] | None = None
    summary: str = ""


class MockMCPClient:
    def __init__(self) -> None:
        self.last_tool_calls: list[ToolCallRecord] = []

    async def list_tool_specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="rag_search",
                description="Search internal company documents.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "document_ids": {"type": "array", "items": {"type": "string"}},
                        "top_k": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            ),
            ToolSpec(
                name="hr_query",
                description="Read the current user's own HR data.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "intent": {
                            "type": "string",
                            "enum": ["leave_balance", "leave_requests", "payroll"],
                        },
                    },
                    "required": ["user_id", "intent"],
                },
            ),
        ]

    async def list_tools(self) -> list[str]:
        return [spec.name for spec in await self.list_tool_specs()]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "rag_search":
            results = await self._mock_rag_search(
                query=str(arguments.get("query", "")),
                document_ids=list(arguments.get("document_ids") or []),
                top_k=int(arguments.get("top_k") or 5),
            )
            return {"results": [result.__dict__ for result in results]}
        if name == "hr_query":
            result = await self._mock_hr_query(
                user_id=str(arguments.get("user_id", "")),
                intent=str(arguments.get("intent", "")),
            )
            payload: dict[str, Any] = {
                "intent": result.intent,
                "summary": result.summary,
            }
            if result.leave_balance is not None:
                payload["leave_balance"] = result.leave_balance.__dict__
            if result.leave_requests is not None:
                payload["leave_requests"] = [item.__dict__ for item in result.leave_requests]
            if result.payroll is not None:
                payload["payroll"] = [item.__dict__ for item in result.payroll]
            return payload
        self.last_tool_calls.append(
            ToolCallRecord(
                tool_name=name,
                arguments=dict(arguments),
            )
        )
        return {"summary": ""}

    async def rag_search(
        self,
        query: str,
        document_ids: list[str],
        top_k: int = 5,
    ) -> list[SearchResult]:
        return await self._mock_rag_search(query=query, document_ids=document_ids, top_k=top_k)

    async def _mock_rag_search(
        self,
        query: str,
        document_ids: list[str],
        top_k: int = 5,
    ) -> list[SearchResult]:
        self.last_tool_calls.append(
            ToolCallRecord(
                tool_name="rag_search",
                arguments={"query": query, "document_ids": list(document_ids), "top_k": top_k},
            )
        )
        if not document_ids:
            return []

        query_lower = query.lower()
        query_tokens = _query_tokens(query)
        results: list[SearchResult] = []
        for document in MOCK_DOCUMENTS:
            if document.id not in document_ids:
                continue
            haystack = " ".join(
                [
                    document.name,
                    document.department,
                    document.caption,
                    document.section_content,
                    " ".join(document.heading_path),
                ]
            )
            haystack_tokens = _token_set(haystack)
            matched_tokens = [
                token
                for token in query_tokens
                if token in haystack_tokens
            ]
            if not matched_tokens:
                score = 0.2
            else:
                score = document.score + min(0.08, len(set(matched_tokens)) * 0.02)
            if "khong lien quan" in _normalize_text(query_lower) or "alien" in query_lower:
                score = 0.2
            results.append(
                SearchResult(
                    chunk_id=f"{document.id}-chunk-1",
                    document_id=document.id,
                    document_name=document.name,
                    caption=document.caption,
                    parent_text=document.section_content,
                    heading_path=document.heading_path,
                    score=min(score, 0.99),
                    page_number=1,
                    source_gcs_uri=document.source_gcs_uri,
                    markdown_gcs_uri=document.source_gcs_uri.replace(".pdf", ".md"),
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)[:top_k]

    async def hr_query(self, user_id: str, intent: str) -> HrQueryResult:
        return await self._mock_hr_query(user_id=user_id, intent=intent)

    async def _mock_hr_query(self, user_id: str, intent: str) -> HrQueryResult:
        self.last_tool_calls.append(
            ToolCallRecord(
                tool_name="hr_query",
                arguments={"user_id": user_id, "intent": intent},
            )
        )
        data = MOCK_HR_DATA.get(user_id, {})
        if not data:
            return HrQueryResult(
                intent=intent,
                summary="Không có dữ liệu HR mock cho user hiện tại.",
            )
        if intent == "leave_requests":
            requests = [
                LeaveRequestDTO(
                    leave_type=str(item["leave_type"]),
                    start_date=str(item["start_date"]),
                    end_date=str(item["end_date"]),
                    days_count=int(item["days_count"]),
                    status=str(item["status"]),
                )
                for item in data.get("leave_requests", [])
            ]
            return HrQueryResult(
                intent=intent,
                leave_requests=requests,
                summary=_leave_requests_summary(requests),
            )
        if intent == "payroll":
            payroll_data = data.get("payroll", {})
            payroll = [
                PayrollDTO(
                    period=str(payroll_data["period"]),
                    gross_salary=float(payroll_data["gross_salary"]),
                    deductions=float(payroll_data["deductions"]),
                    net_salary=float(payroll_data["net_salary"]),
                )
            ]
            return HrQueryResult(
                intent=intent,
                payroll=payroll,
                summary=_payroll_summary(payroll[0]),
            )
        balance_data = data.get("leave_balance", {})
        balance = LeaveBalanceDTO(
            annual_total=int(balance_data["annual_leave_total"]),
            annual_used=int(balance_data["annual_leave_used"]),
            annual_remaining=int(balance_data["annual_leave_remaining"]),
            sick_total=int(balance_data["sick_leave_total"]),
            sick_used=int(balance_data["sick_leave_used"]),
            sick_remaining=int(balance_data["sick_leave_total"]) - int(balance_data["sick_leave_used"]),
        )
        return HrQueryResult(
            intent="leave_balance",
            leave_balance=balance,
            summary=_leave_balance_summary(balance),
        )

    def reset(self) -> None:
        self.last_tool_calls.clear()


class MCPStreamableHttpClient:
    def __init__(self, settings: Settings) -> None:
        self._endpoint_url = _mcp_endpoint_url(settings.mcp_service_url)
        self._timeout_seconds = settings.mcp_timeout_seconds
        self._internal_token = (settings.mcp_internal_token or "").strip()

    async def list_tool_specs(self) -> list[ToolSpec]:
        async with self._session() as session:
            tools_response = await session.list_tools()
        tools = getattr(tools_response, "tools", [])
        specs: list[ToolSpec] = []
        for tool in tools:
            if isinstance(tool, str):
                specs.append(ToolSpec(name=tool, description="", input_schema={}))
                continue
            if isinstance(tool, dict):
                specs.append(
                    ToolSpec(
                        name=str(tool.get("name") or ""),
                        description=str(tool.get("description") or ""),
                        input_schema=dict(tool.get("inputSchema") or tool.get("input_schema") or {}),
                    )
                )
                continue
            specs.append(
                ToolSpec(
                    name=str(getattr(tool, "name", "") or ""),
                    description=str(getattr(tool, "description", "") or ""),
                    input_schema=dict(
                        getattr(tool, "inputSchema", None)
                        or getattr(tool, "input_schema", None)
                        or {}
                    ),
                )
            )
        return [spec for spec in specs if spec.name]

    async def list_tools(self) -> list[str]:
        return [spec.name for spec in await self.list_tool_specs()]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._call_tool(name, arguments)
        payload = _extract_tool_payload(result)
        if isinstance(payload, dict):
            return payload
        return {}

    async def rag_search(
        self,
        query: str,
        document_ids: list[str],
        top_k: int = 5,
    ) -> list[SearchResult]:
        payload = await self.call_tool(
            "rag_search",
            {
                "query": query,
                "document_ids": list(document_ids),
                "top_k": top_k,
            },
        )
        raw_results = payload.get("results", payload if isinstance(payload, list) else [])
        if not isinstance(raw_results, list):
            return []
        return [_search_result_from_payload(item) for item in raw_results if isinstance(item, dict)]

    async def hr_query(self, user_id: str, intent: str) -> HrQueryResult:
        payload = await self.call_tool(
            "hr_query",
            {
                "user_id": user_id,
                "intent": intent,
            },
        )
        return _hr_result_from_payload(payload, intent)

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        async with self._session() as session:
            result = await session.call_tool(name, arguments=arguments)
        if bool(getattr(result, "isError", False)):
            raise RuntimeError(f"MCP tool {name} returned an error")
        return _call_tool_result_payload(result)

    def _session(self):
        return _McpSessionContext(self._endpoint_url, self._timeout_seconds, self._internal_token)


class _McpSessionContext:
    def __init__(self, endpoint_url: str, timeout_seconds: int, internal_token: str = "") -> None:
        self._endpoint_url = endpoint_url
        self._timeout_seconds = timeout_seconds
        self._internal_token = internal_token
        self._http_client = None
        self._transport_cm = None
        self._session_cm = None
        self._session = None

    async def __aenter__(self):
        session_cls, transport_factory = _sdk_objects()
        headers = {}
        if self._internal_token:
            headers[MCP_INTERNAL_TOKEN_HEADER] = self._internal_token
        self._http_client = httpx.AsyncClient(timeout=self._timeout_seconds, headers=headers)
        self._transport_cm = transport_factory(self._endpoint_url, http_client=self._http_client)
        read_stream, write_stream, _ = await self._transport_cm.__aenter__()
        self._session_cm = session_cls(read_stream, write_stream)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if self._session_cm is not None:
                await self._session_cm.__aexit__(exc_type, exc, tb)
            if self._transport_cm is not None:
                await self._transport_cm.__aexit__(exc_type, exc, tb)
        finally:
            if self._http_client is not None:
                await self._http_client.aclose()


def _sdk_objects():
    global ClientSession, streamable_http_client
    if ClientSession is None or streamable_http_client is None:
        try:
            from mcp import ClientSession as sdk_client_session
            from mcp.client.streamable_http import streamable_http_client as sdk_streamable_http_client
        except ImportError as exc:
            raise RuntimeError("mcp>=1.27,<2 is required for MCP_MODE=real") from exc
        ClientSession = sdk_client_session
        streamable_http_client = sdk_streamable_http_client
    return ClientSession, streamable_http_client


def _leave_balance_summary(balance: LeaveBalanceDTO) -> str:
    return (
        f"Bạn còn {balance.annual_remaining} ngày nghỉ phép năm "
        f"và {balance.sick_remaining} ngày nghỉ ốm."
    )


def _leave_requests_summary(requests: list[LeaveRequestDTO]) -> str:
    if not requests:
        return "Bạn chưa có đơn nghỉ phép nào trong mock data."
    latest = requests[0]
    return (
        f"Đơn nghỉ gần nhất là {latest.days_count} ngày từ {latest.start_date} "
        f"đến {latest.end_date}, trạng thái {latest.status}."
    )


def _payroll_summary(payroll: PayrollDTO) -> str:
    return (
        f"Kỳ lương {payroll.period}: lương gross {payroll.gross_salary:,.0f}, "
        f"khấu trừ {payroll.deductions:,.0f}, net {payroll.net_salary:,.0f}."
    )


STOPWORDS = {
    "ai",
    "anh",
    "an",
    "ăn",
    "ban",
    "bạn",
    "cai",
    "cái",
    "cho",
    "co",
    "có",
    "cua",
    "của",
    "duoc",
    "được",
    "gi",
    "gì",
    "hom",
    "hôm",
    "la",
    "là",
    "nay",
    "nhu",
    "như",
    "toi",
    "tôi",
    "ve",
    "về",
    "what",
    "who",
    "you",
    "are",
    "is",
}


def _query_tokens(text: str) -> list[str]:
    tokens = _token_set(text)
    return sorted(token for token in tokens if len(token) > 1 and token not in STOPWORDS)


def _token_set(text: str) -> set[str]:
    raw_tokens = re.findall(r"\w+", text.lower().replace("_", " "), re.UNICODE)
    normalized_tokens = re.findall(r"\w+", _normalize_text(text), re.UNICODE)
    return set(raw_tokens) | set(normalized_tokens)


def _normalize_text(text: str) -> str:
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(character)
    )
    without_punctuation = re.sub(r"[_\W]+", " ", without_accents, flags=re.UNICODE)
    return re.sub(r"\s+", " ", without_punctuation).strip()


def _mcp_endpoint_url(service_url: str) -> str:
    base = service_url.rstrip("/")
    if base.endswith("/mcp"):
        return base
    return f"{base}/mcp"


def _extract_tool_payload(result: dict[str, Any]) -> Any:
    if "structuredContent" in result:
        return result["structuredContent"]
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if "json" in item:
                return item["json"]
            text = item.get("text")
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except ValueError:
                    continue
    return result


def _call_tool_result_payload(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    content = getattr(result, "content", None)
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                if "json" in item:
                    return item["json"]
                text = item.get("text")
            else:
                text = getattr(item, "text", None)
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except ValueError:
                    continue
    return {}


def _search_result_from_payload(item: dict[str, Any]) -> SearchResult:
    return SearchResult(
        chunk_id=str(
            item.get("chunk_id") or item.get("section_id") or item.get("node_id") or item.get("unit_id") or ""
        ),
        document_id=str(item.get("document_id", "")),
        document_name=str(item.get("document_name") or item.get("display_name") or ""),
        caption=str(item.get("caption", "")),
        parent_text=str(item.get("parent_text") or item.get("section_content") or item.get("content") or ""),
        heading_path=list(item.get("heading_path") or []),
        score=float(item.get("score") or item.get("rerank_score") or 0.0),
        page_number=item.get("page_number"),
        source_gcs_uri=str(
            item.get("source_gcs_uri")
            or item.get("source_s3_uri")
            or (item.get("lineage", {}) or {}).get("source_uri")
            or ""
        ),
        markdown_gcs_uri=str(
            item.get("markdown_gcs_uri")
            or item.get("markdown_s3_uri")
            or (item.get("lineage", {}) or {}).get("artifact_uri")
            or ""
        ),
    )


def _hr_result_from_payload(payload: dict[str, Any], requested_intent: str) -> HrQueryResult:
    leave_balance = None
    if isinstance(payload.get("leave_balance"), dict):
        balance = payload["leave_balance"]
        leave_balance = LeaveBalanceDTO(
            annual_total=int(balance.get("annual_total") or balance.get("annual_leave_total") or 0),
            annual_used=int(balance.get("annual_used") or balance.get("annual_leave_used") or 0),
            annual_remaining=int(
                balance.get("annual_remaining") or balance.get("annual_leave_remaining") or 0
            ),
            sick_total=int(balance.get("sick_total") or balance.get("sick_leave_total") or 0),
            sick_used=int(balance.get("sick_used") or balance.get("sick_leave_used") or 0),
            sick_remaining=int(balance.get("sick_remaining") or 0),
        )

    leave_requests = None
    if isinstance(payload.get("leave_requests"), list):
        leave_requests = [
            LeaveRequestDTO(
                leave_type=str(item.get("leave_type", "")),
                start_date=str(item.get("start_date", "")),
                end_date=str(item.get("end_date", "")),
                days_count=int(item.get("days_count", 0)),
                status=str(item.get("status", "")),
            )
            for item in payload["leave_requests"]
            if isinstance(item, dict)
        ]

    payroll = None
    if isinstance(payload.get("payroll"), list):
        payroll = [
            PayrollDTO(
                period=str(item.get("period", "")),
                gross_salary=float(item.get("gross_salary", 0.0)),
                deductions=float(item.get("deductions", 0.0)),
                net_salary=float(item.get("net_salary", 0.0)),
            )
            for item in payload["payroll"]
            if isinstance(item, dict)
        ]

    return HrQueryResult(
        intent=str(payload.get("intent") or requested_intent),
        leave_balance=leave_balance,
        leave_requests=leave_requests,
        payroll=payroll,
        summary=str(payload.get("summary", "")),
    )
