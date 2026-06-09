from dataclasses import dataclass
import json
import re
import time
from typing import Any
import unicodedata

import httpx

from app.application.ports import ToolSpec
from app.infrastructure.db.mock_data import MOCK_DOCUMENTS, MOCK_HR_DATA
from app.infrastructure.config import Settings

streamable_http_client = None
ClientSession = None

MCP_INTERNAL_TOKEN_HEADER = "X-Internal-Token"

# Params injected server-side — never exposed in the tool schema shown to the model.
_RESERVED_PARAMS: frozenset[str] = frozenset({"user_id", "document_ids", "top_k"})

# Static tool specs for mock mode (reserved params already stripped).
_MOCK_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="rag_search",
        description="Tìm kiếm thông tin trong tài liệu nội bộ của công ty.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Câu hỏi hoặc từ khóa cần tìm kiếm"},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="hr_query",
        description="Truy vấn thông tin HR cá nhân: số ngày nghỉ phép, lịch sử đơn nghỉ, bảng lương.",
        input_schema={
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["leave_balance", "leave_requests", "payroll"],
                    "description": "Loại thông tin HR cần truy vấn",
                },
            },
            "required": ["intent"],
        },
    ),
]


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

    @property
    def is_circuit_open(self) -> bool:
        return False

    async def list_tools(self) -> list[str]:
        return ["rag_search", "hr_query"]

    async def list_tool_specs(self) -> list[ToolSpec]:
        return list(_MOCK_TOOL_SPECS)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "rag_search":
            query = str(arguments.get("query", ""))
            document_ids = list(arguments.get("document_ids", []))
            top_k = int(arguments.get("top_k", 5))
            results = await self.rag_search(query=query, document_ids=document_ids, top_k=top_k)
            return {
                "results": [
                    {
                        "chunk_id": r.chunk_id,
                        "document_id": r.document_id,
                        "document_name": r.document_name,
                        "caption": r.caption,
                        "parent_text": r.parent_text,
                        "heading_path": r.heading_path,
                        "score": r.score,
                    }
                    for r in results
                ]
            }
        if name == "hr_query":
            user_id = str(arguments.get("user_id", ""))
            intent = str(arguments.get("intent", "leave_balance"))
            result = await self.hr_query(user_id=user_id, intent=intent)
            return {"summary": result.summary, "intent": result.intent}
        return {"error": f"Unknown tool: {name}"}

    async def rag_search(
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


class MCPCircuitOpenError(RuntimeError):
    """Raised when the MCP circuit breaker is open and calls are blocked."""


class MCPStreamableHttpClient:
    def __init__(self, settings: Settings) -> None:
        self._endpoint_url = _mcp_endpoint_url(settings.mcp_service_url)
        self._timeout_seconds = settings.mcp_timeout_seconds
        self._internal_token = (settings.mcp_internal_token or "").strip()
        self._breaker = _build_circuit_breaker(
            fail_max=settings.mcp_circuit_fail_max,
            reset_timeout=settings.mcp_circuit_reset_timeout_seconds,
        )
        self._tool_specs_cache: list[ToolSpec] | None = None
        self._tool_specs_cache_at: float = 0.0
        self._tool_specs_ttl: int = settings.mcp_tool_cache_ttl_seconds

    @property
    def is_circuit_open(self) -> bool:
        return bool(getattr(self._breaker, "current_state", "closed") == "open")

    async def list_tools(self) -> list[str]:
        specs = await self.list_tool_specs()
        return [spec.name for spec in specs]

    async def list_tool_specs(self) -> list[ToolSpec]:
        now = time.monotonic()
        if (
            self._tool_specs_cache is not None
            and self._tool_specs_ttl > 0
            and now - self._tool_specs_cache_at < self._tool_specs_ttl
        ):
            return self._tool_specs_cache
        async with self._session() as session:
            tools_response = await session.list_tools()
        raw_tools = getattr(tools_response, "tools", [])
        specs: list[ToolSpec] = []
        for tool in raw_tools:
            if isinstance(tool, str):
                specs.append(ToolSpec(name=tool, description="", input_schema={}))
                continue
            name = (tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)) or ""
            if not name:
                continue
            description = str(
                (tool.get("description") if isinstance(tool, dict) else getattr(tool, "description", "")) or ""
            )
            raw_schema: dict = (
                (tool.get("inputSchema") or tool.get("input_schema") or {})
                if isinstance(tool, dict)
                else (getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {})
            )
            if isinstance(raw_schema, dict):
                raw_schema = _strip_reserved_params(raw_schema)
            specs.append(ToolSpec(name=str(name), description=description, input_schema=raw_schema))
        self._tool_specs_cache = specs
        self._tool_specs_cache_at = now
        return specs

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._call_tool(name, arguments)
        if isinstance(result, dict):
            return result
        return {}

    async def rag_search(
        self,
        query: str,
        document_ids: list[str],
        top_k: int = 5,
    ) -> list[SearchResult]:
        result = await self._call_tool(
            "rag_search",
            {
                "query": query,
                "document_ids": list(document_ids),
                "top_k": top_k,
            },
        )
        payload = _extract_tool_payload(result)
        raw_results = payload.get("results", payload if isinstance(payload, list) else [])
        if not isinstance(raw_results, list):
            return []
        return [_search_result_from_payload(item) for item in raw_results if isinstance(item, dict)]

    async def hr_query(self, user_id: str, intent: str) -> HrQueryResult:
        result = await self._call_tool(
            "hr_query",
            {
                "user_id": user_id,
                "intent": intent,
            },
        )
        payload = _extract_tool_payload(result)
        if not isinstance(payload, dict):
            payload = {}
        return _hr_result_from_payload(payload, intent)

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        pybreaker = _import_pybreaker()
        try:
            return await self._breaker.call_async(self._call_tool_inner, name, arguments)
        except pybreaker.CircuitBreakerError as exc:
            raise MCPCircuitOpenError(
                f"MCP circuit breaker is open — calls to {name} are blocked"
            ) from exc

    async def _call_tool_inner(self, name: str, arguments: dict[str, Any]) -> Any:
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


def _strip_reserved_params(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove server-injected params from a JSON Schema so the model never sees them."""
    props = schema.get("properties", {})
    if not props or not (_RESERVED_PARAMS & props.keys()):
        return schema
    new_props = {k: v for k, v in props.items() if k not in _RESERVED_PARAMS}
    result: dict[str, Any] = {**schema, "properties": new_props}
    if "required" in schema:
        result["required"] = [r for r in schema["required"] if r not in _RESERVED_PARAMS]
    return result


def _import_pybreaker():
    try:
        import pybreaker
    except ImportError as exc:
        raise RuntimeError("pybreaker is required for the MCP circuit breaker") from exc
    return pybreaker


def _build_circuit_breaker(fail_max: int, reset_timeout: int):
    pybreaker = _import_pybreaker()
    return pybreaker.CircuitBreaker(fail_max=fail_max, reset_timeout=reset_timeout)


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
