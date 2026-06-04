from dataclasses import dataclass
import re
from typing import Any
import unicodedata

from app.infrastructure.db.mock_data import MOCK_DOCUMENTS, MOCK_HR_DATA


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
    source_s3_uri: str = ""
    markdown_s3_uri: str = ""


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

    async def list_tools(self) -> list[str]:
        return ["rag_search", "hr_query"]

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
                    source_s3_uri=document.source_s3_uri,
                    markdown_s3_uri=document.source_s3_uri.replace(".pdf", ".md"),
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
