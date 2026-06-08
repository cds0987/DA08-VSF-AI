from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
import re
import unicodedata
from typing import Protocol

from app.infrastructure.config import Settings


VALID_INTENTS = {
    "identity",
    "clarification",
    "out_of_scope",
    "hr:payroll",
    "hr:leave_requests",
    "hr:leave_balance",
    "rag",
}


@dataclass(frozen=True)
class IntentClassification:
    intent: str
    confidence: float
    source: str
    reason: str = ""


class IntentEmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class IntentLLMClient(Protocol):
    async def classify(
        self,
        question: str,
        recent_messages: Sequence[tuple[str, str]] | None = None,
    ) -> IntentClassification:
        ...


@dataclass(frozen=True)
class RulePattern:
    intent: str
    phrases: tuple[str, ...]


RULE_PATTERNS = (
    RulePattern(
        intent="identity",
        phrases=(
            "ban la ai",
            "ban lam duoc gi",
            "ban co the lam gi",
            "gioi thieu ve ban",
            "ai tao ra ban",
            "who are you",
            "what can you do",
            "who created you",
        ),
    ),
    RulePattern(
        intent="clarification",
        phrases=(
            "alo",
            "hello",
            "hi",
            "xin chao",
            "chao",
            "mat bi sao vay",
            "cai mat ong ay",
            "tai sao lai the",
            "tai sao the",
            "mat ban bi dinh hat com kia",
        ),
    ),
    RulePattern(
        intent="out_of_scope",
        phrases=(
            "mat khau",
            "password",
            "secret key",
            "api key",
            "access token",
            "refresh token",
            "credentials",
            "thong tin dang nhap",
        ),
    ),
    RulePattern(
        intent="hr:payroll",
        phrases=(
            "luong",
            "payroll",
            "khau tru",
            "phieu luong",
            "bang luong",
            "salary",
            "payslip",
            "net salary",
            "gross salary",
        ),
    ),
    RulePattern(
        intent="hr:leave_requests",
        phrases=(
            "don nghi",
            "leave request",
            "trang thai nghi",
            "leave status",
        ),
    ),
    RulePattern(
        intent="hr:leave_balance",
        phrases=(
            "ngay nghi",
            "nghi phep con",
            "bao nhieu ngay nghi",
            "con bao nhieu ngay nghi",
            "leave balance",
            "remaining leave",
            "leave left",
            "pto balance",
        ),
    ),
    RulePattern(
        intent="rag",
        phrases=(
            "chinh sach",
            "quy trinh",
            "quy dinh",
            "tai lieu",
            "policy",
            "procedure",
            "guideline",
            "handbook",
            "onboarding",
        ),
    ),
)


EMBEDDING_PROTOTYPES: dict[str, tuple[str, ...]] = {
    "identity": (
        "who are you",
        "what can this assistant do",
    ),
    "clarification": (
        "hello",
        "i do not understand this context",
    ),
    "out_of_scope": (
        "admin password",
        "share internal credentials",
    ),
    "hr:payroll": (
        "salary payroll deduction",
        "monthly salary and payslip",
    ),
    "hr:leave_requests": (
        "leave request approval status",
        "status of my time off request",
    ),
    "hr:leave_balance": (
        "remaining leave balance",
        "vacation days left",
    ),
    "rag": (
        "leave policy and company handbook",
        "onboarding procedure and internal guideline",
    ),
}


class HybridIntentClassifier:
    def __init__(
        self,
        settings: Settings,
        *,
        embedding_client: IntentEmbeddingClient | None = None,
        llm_client: IntentLLMClient | None = None,
    ) -> None:
        self._settings = settings
        self._embedding_client = embedding_client
        self._llm_client = llm_client
        self._prototype_vectors: list[tuple[str, list[float]]] | None = None

    async def classify(
        self,
        question: str,
        recent_messages: Sequence[tuple[str, str]] | None = None,
    ) -> IntentClassification:
        rule_result = self._classify_by_rules(question)
        if (
            rule_result is not None
            and rule_result.confidence >= self._settings.intent_rule_confidence_threshold
        ):
            return rule_result

        mode = self._settings.intent_classifier_mode.strip().lower()
        if mode == "rules":
            return rule_result or self._fallback("rules mode found no confident rule")

        if mode == "hybrid":
            embedding_result = await self._classify_by_embedding(question)
            if embedding_result is not None:
                return embedding_result

        if mode in {"hybrid", "llm"}:
            llm_result = await self._classify_by_llm(question, recent_messages)
            if llm_result is not None:
                return llm_result

        return self._fallback("no classifier produced a confident result")

    def _classify_by_rules(self, question: str) -> IntentClassification | None:
        normalized = _normalize_text(question)
        for pattern in RULE_PATTERNS:
            for phrase in pattern.phrases:
                if _contains_phrase(normalized, phrase):
                    return IntentClassification(
                        intent=pattern.intent,
                        confidence=0.95,
                        source="rule",
                        reason=f"matched phrase: {phrase}",
                    )
        return None

    async def _classify_by_embedding(self, question: str) -> IntentClassification | None:
        if self._embedding_client is None:
            return None
        try:
            await self._ensure_prototype_vectors()
            assert self._prototype_vectors is not None
            question_vectors = await self._embedding_client.embed([question])
        except Exception:
            return None
        if not question_vectors:
            return None
        question_vector = question_vectors[0]
        scores_by_intent: dict[str, float] = {}
        for intent, prototype_vector in self._prototype_vectors:
            score = _cosine_similarity(question_vector, prototype_vector)
            scores_by_intent[intent] = max(scores_by_intent.get(intent, 0.0), score)
        scored = sorted(scores_by_intent.items(), key=lambda item: item[1], reverse=True)
        if not scored:
            return None
        top_intent, top_score = scored[0]
        next_score = scored[1][1] if len(scored) > 1 else 0.0
        if top_score < self._settings.intent_embedding_confidence_threshold:
            return None
        if top_score - next_score < self._settings.intent_embedding_margin:
            return None
        return IntentClassification(
            intent=top_intent,
            confidence=round(top_score, 4),
            source="embedding",
            reason="nearest prototype by cosine similarity",
        )

    async def _classify_by_llm(
        self,
        question: str,
        recent_messages: Sequence[tuple[str, str]] | None,
    ) -> IntentClassification | None:
        if self._llm_client is None:
            return None
        try:
            result = await self._llm_client.classify(question, recent_messages)
        except Exception:
            return None
        if result.intent not in VALID_INTENTS:
            return None
        if result.confidence < self._settings.intent_llm_confidence_threshold:
            return None
        return IntentClassification(
            intent=result.intent,
            confidence=min(1.0, max(0.0, result.confidence)),
            source="llm",
            reason=result.reason,
        )

    async def _ensure_prototype_vectors(self) -> None:
        if self._prototype_vectors is not None:
            return
        if self._embedding_client is None:
            self._prototype_vectors = []
            return
        prototype_items = [
            (intent, prototype)
            for intent, prototypes in EMBEDDING_PROTOTYPES.items()
            for prototype in prototypes
        ]
        vectors = await self._embedding_client.embed([text for _, text in prototype_items])
        self._prototype_vectors = [
            (intent, vector)
            for (intent, _), vector in zip(prototype_items, vectors)
        ]

    @staticmethod
    def _fallback(reason: str) -> IntentClassification:
        return IntentClassification(
            intent="rag",
            confidence=0.0,
            source="fallback",
            reason=reason,
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


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)
