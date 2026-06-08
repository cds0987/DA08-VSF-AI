from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re
import unicodedata

from app.application.intent_classifier import HybridIntentClassifier, IntentClassification
from app.application.route_decision import RouteDecision, coerce_route_decision
from app.application.tool_decision import ToolDecision
from app.infrastructure.config import Settings


IDENTITY_PHRASES = (
    "ban la ai",
    "ban lam duoc gi",
    "ban co the lam gi",
    "gioi thieu ve ban",
    "ai tao ra ban",
    "who are you",
    "what can you do",
    "who created you",
)

GREETING_PHRASES = (
    "alo",
    "hello",
    "hi",
    "xin chao",
    "chao",
)

CLARIFICATION_PHRASES = (
    "mat bi sao vay",
    "cai mat ong ay",
    "tai sao lai the",
    "tai sao the",
    "mat ban bi dinh hat com kia",
)

SECURITY_PHRASES = (
    "mat khau",
    "password",
    "admin password",
    "secret key",
    "api key",
    "access token",
    "refresh token",
    "credentials",
    "thong tin dang nhap",
)

POLICY_PHRASES = (
    "chinh sach",
    "quy trinh",
    "quy dinh",
    "tai lieu",
    "noi quy",
    "policy",
    "procedure",
    "guideline",
    "handbook",
    "onboarding",
)

PERSONAL_HR_PHRASES = (
    "toi con bao nhieu ngay nghi",
    "con bao nhieu ngay nghi",
    "nghi phep con",
    "remaining leave",
    "leave left",
    "leave balance",
    "pto balance",
    "my leave",
    "phieu luong",
    "bang luong",
    "salary",
    "payroll",
    "payslip",
    "leave request",
    "leave status",
    "don nghi cua toi",
    "trang thai nghi cua toi",
)

ENGLISH_HINTS = {
    "who",
    "what",
    "why",
    "how",
    "policy",
    "procedure",
    "guideline",
    "leave",
    "remaining",
    "salary",
    "payroll",
    "hello",
    "hi",
    "password",
}

OFF_TOPIC_KEYWORDS = (
    # Vietnamese
    "mua gi",
    "can mua",
    "noi ban",
    "gia bao nhieu",
    "cong thuc",
    "cach lam",
    "cach nau",
    "thoi tiet",
    "nha hang",
    "an uong",
    "di dau",
    "choi gi",
    "di cho",
    "ban o dau",
    "tim nha",
    "du lich",
    # English
    "buy",
    "shop",
    "order",
    "recipe",
    "cook",
    "restaurant",
    "weather",
    "lunch",
    "dinner",
    "breakfast",
    "eat",
    "travel",
    "tourist",
    "movie",
    "game",
    "sport",
)


@dataclass(frozen=True)
class ShortcutMatch:
    route: str
    kind: str


class QueryRouter:
    def __init__(
        self,
        settings: Settings,
        intent_classifier: HybridIntentClassifier,
    ) -> None:
        self._settings = settings
        self._intent_classifier = intent_classifier
        self._forced_decisions: list[RouteDecision | ToolDecision] = []

    async def choose_route(
        self,
        question: str,
        recent_messages: Sequence[tuple[str, str]],
        available_tools: Sequence[str],
    ) -> RouteDecision:
        if self._forced_decisions:
            return coerce_route_decision(
                self._forced_decisions.pop(0),
                default_query=question,
            )

        shortcut = self._shortcut_route(question)
        if shortcut is not None:
            return self._shortcut_decision(question, shortcut)

        classification = await self._intent_classifier.classify(question, recent_messages)
        decision = self._from_classification(question, classification)
        if decision.decision == "hr_query" and "hr_query" not in set(available_tools):
            return RouteDecision(
                decision="rag_search",
                tool_arguments={"query": question},
                reason="hr_query unavailable",
                confidence=0.0,
            )
        if decision.decision == "rag_search" and "rag_search" not in set(available_tools):
            return self._clarification_response(
                question,
                reason="rag_search unavailable",
                confidence=0.0,
            )
        return decision

    async def choose_tool(
        self,
        question: str,
        recent_messages: Sequence[tuple[str, str]],
        available_tools: Sequence[str],
    ) -> ToolDecision:
        route = await self.choose_route(question, recent_messages, available_tools)
        if route.decision == "hr_query":
            return ToolDecision(
                tool_name="hr_query",
                arguments={"intent": str(route.tool_arguments["intent"])},
                reason=route.reason,
            )
        return ToolDecision(
            tool_name="rag_search",
            arguments={"query": str(route.tool_arguments.get("query") or question)},
            reason=route.reason,
        )

    def force_next_decision(self, decision: RouteDecision | ToolDecision) -> None:
        self._forced_decisions.append(decision)

    def reset(self) -> None:
        self._forced_decisions.clear()

    def _shortcut_route(self, question: str) -> ShortcutMatch | None:
        normalized = _normalize_text(question)

        if any(_contains_phrase(normalized, phrase) for phrase in IDENTITY_PHRASES):
            return ShortcutMatch(route="identity_shortcut", kind="identity")

        if self._is_mixed_query(normalized):
            return ShortcutMatch(route="out_of_scope", kind="mixed")

        if any(_contains_phrase(normalized, phrase) for phrase in SECURITY_PHRASES):
            return ShortcutMatch(route="out_of_scope", kind="security")

        if normalized in GREETING_PHRASES or any(_contains_phrase(normalized, phrase) for phrase in CLARIFICATION_PHRASES):
            return ShortcutMatch(route="clarification", kind="clarification")

        if self._is_off_topic(normalized):
            return ShortcutMatch(route="off_topic", kind="off_topic")

        if len(normalized.split()) <= 2 and normalized in GREETING_PHRASES:
            return ShortcutMatch(route="clarification", kind="greeting")

        return None

    def _shortcut_decision(self, question: str, shortcut: ShortcutMatch) -> RouteDecision:
        if shortcut.route == "identity_shortcut":
            return self._identity_response(question, confidence=1.0)
        if shortcut.kind == "security":
            return self._security_response(question, confidence=1.0)
        if shortcut.kind == "mixed":
            return self._mixed_query_response(question, confidence=1.0)
        if shortcut.kind == "off_topic":
            return self._off_topic_response(question, confidence=1.0)
        return self._clarification_response(question, reason=shortcut.kind, confidence=1.0)

    def _identity_response(
        self,
        question: str,
        *,
        confidence: float,
        reason: str = "identity shortcut",
    ) -> RouteDecision:
        if _looks_english(question):
            answer = (
                "I am VinSmartFuture's internal assistant. I answer using internal documents "
                "and the data you are allowed to access."
            )
        else:
            answer = (
                "Minh la tro ly noi bo VinSmartFuture, ho tro tra loi dua tren tai lieu noi bo "
                "va du lieu ban duoc cap quyen truy cap."
            )
        return RouteDecision(
            decision="identity_shortcut",
            direct_response=answer,
            reason=reason,
            confidence=confidence,
        )

    def _clarification_response(
        self,
        question: str,
        *,
        reason: str,
        confidence: float,
    ) -> RouteDecision:
        normalized = _normalize_text(question)
        if _looks_english(question):
            answer = "I do not have enough context yet. Please clarify or ask the full question."
        elif normalized in GREETING_PHRASES:
            answer = "Chao ban, minh co the ho tro gi? Ban hay noi ro cau hoi giup minh nhe."
        else:
            answer = "Minh chua du ngu canh de tra loi. Ban co the noi ro hon hoac dat cau hoi day du giup minh khong?"
        return RouteDecision(
            decision="clarification",
            direct_response=answer,
            reason=reason,
            confidence=confidence,
        )

    def _security_response(
        self,
        question: str,
        *,
        confidence: float,
        reason: str = "security refusal",
    ) -> RouteDecision:
        if _looks_english(question):
            answer = "I cannot provide passwords, credentials, tokens, or other internal secrets."
        else:
            answer = "Minh khong the cung cap mat khau, thong tin dang nhap, token, hoac bi mat noi bo."
        return RouteDecision(
            decision="out_of_scope",
            direct_response=answer,
            reason=reason,
            confidence=confidence,
        )

    def _mixed_query_response(
        self,
        question: str,
        *,
        confidence: float,
        reason: str = "mixed query",
    ) -> RouteDecision:
        if _looks_english(question):
            answer = (
                "Your question mixes a policy lookup with personal HR data. "
                "Please split it into separate questions."
            )
        else:
            answer = (
                "Cau hoi nay dang tron tra cuu chinh sach voi du lieu HR ca nhan. "
                "Ban vui long tach thanh tung cau hoi rieng."
            )
        return RouteDecision(
            decision="out_of_scope",
            direct_response=answer,
            reason=reason,
            confidence=confidence,
        )

    def _is_mixed_query(self, normalized: str) -> bool:
        has_policy = any(_contains_phrase(normalized, phrase) for phrase in POLICY_PHRASES)
        has_personal_hr = any(_contains_phrase(normalized, phrase) for phrase in PERSONAL_HR_PHRASES)
        return has_policy and has_personal_hr

    def _is_off_topic(self, normalized: str) -> bool:
        if not any(_contains_phrase(normalized, kw) for kw in OFF_TOPIC_KEYWORDS):
            return False
        if any(_contains_phrase(normalized, phrase) for phrase in POLICY_PHRASES):
            return False
        if any(_contains_phrase(normalized, phrase) for phrase in PERSONAL_HR_PHRASES):
            return False
        return True

    def _off_topic_response(
        self,
        question: str,
        *,
        confidence: float,
        reason: str = "off_topic shortcut",
    ) -> RouteDecision:
        if _looks_english(question):
            answer = (
                "Your question is outside the scope of our internal HR and policy assistant. "
                "I can only help with company policies, HR matters, and internal documents."
            )
        else:
            answer = (
                "Câu hỏi của bạn nằm ngoài phạm vi hệ thống HR và tài liệu nội bộ. "
                "Tôi chỉ hỗ trợ về chính sách công ty, HR và thông tin nội bộ."
            )
        return RouteDecision(
            decision="off_topic",
            direct_response=answer,
            reason=reason,
            confidence=confidence,
        )

    def _from_classification(
        self,
        question: str,
        classification: IntentClassification,
    ) -> RouteDecision:
        intent = classification.intent
        confidence = classification.confidence
        reason = classification.reason or classification.source

        if intent == "identity":
            return self._identity_response(question, confidence=confidence, reason=reason)
        if intent == "clarification":
            return self._clarification_response(question, confidence=confidence, reason=reason)
        if intent == "out_of_scope":
            return self._security_response(question, confidence=confidence, reason=reason)
        if intent == "off_topic":
            return self._off_topic_response(question, confidence=confidence, reason=reason)
        if intent == "hr:leave_balance":
            return RouteDecision(
                decision="hr_query",
                tool_arguments={"intent": "leave_balance"},
                reason=reason,
                confidence=confidence,
            )
        if intent == "hr:leave_requests":
            return RouteDecision(
                decision="hr_query",
                tool_arguments={"intent": "leave_requests"},
                reason=reason,
                confidence=confidence,
            )
        if intent == "hr:payroll":
            return RouteDecision(
                decision="hr_query",
                tool_arguments={"intent": "payroll"},
                reason=reason,
                confidence=confidence,
            )
        return RouteDecision(
            decision="rag_search",
            tool_arguments={"query": question},
            reason=reason,
            confidence=confidence,
        )


def _contains_phrase(normalized_text: str, normalized_phrase: str) -> bool:
    escaped = re.escape(normalized_phrase)
    return re.search(rf"(?<!\w){escaped}(?!\w)", normalized_text) is not None


def _normalize_text(text: str) -> str:
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(character)
    )
    without_punctuation = re.sub(r"[_\W]+", " ", without_accents, flags=re.UNICODE)
    return re.sub(r"\s+", " ", without_punctuation).strip()


def _looks_english(text: str) -> bool:
    normalized = _normalize_text(text)
    tokens = set(normalized.split())
    return bool(tokens & ENGLISH_HINTS)
