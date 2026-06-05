import pytest

from app.application.intent_classifier import (
    HybridIntentClassifier,
    IntentClassification,
)
from app.infrastructure.config import Settings


class FakeEmbeddingClient:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            normalized = text.lower()
            if any(token in normalized for token in ["remaining leave", "vacation", "pto"]):
                vectors.append([1.0, 0.0, 0.0])
            elif "salary" in normalized:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


class FakeLLMClient:
    def __init__(self, result: IntentClassification | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[str] = []

    async def classify(self, question: str, recent_messages=None) -> IntentClassification:
        self.calls.append(question)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@pytest.mark.asyncio
async def test_rule_classifier_handles_identity_without_embedding_or_llm() -> None:
    llm_client = FakeLLMClient(
        IntentClassification(intent="hr:payroll", confidence=0.99, source="llm")
    )
    classifier = HybridIntentClassifier(
        Settings(_env_file=None, intent_classifier_mode="hybrid"),
        embedding_client=FakeEmbeddingClient(),
        llm_client=llm_client,
    )

    result = await classifier.classify("Ban la ai?")

    assert result.intent == "identity"
    assert result.source == "rule"
    assert result.confidence >= 0.9
    assert llm_client.calls == []


@pytest.mark.asyncio
async def test_embedding_classifier_catches_paraphrased_leave_balance_question() -> None:
    classifier = HybridIntentClassifier(
        Settings(
            _env_file=None,
            intent_classifier_mode="hybrid",
            intent_embedding_confidence_threshold=0.70,
            intent_embedding_margin=0.05,
        ),
        embedding_client=FakeEmbeddingClient(),
        llm_client=FakeLLMClient(
            IntentClassification(intent="rag", confidence=0.99, source="llm")
        ),
    )

    result = await classifier.classify("How much remaining leave do I still have?")

    assert result.intent == "hr:leave_balance"
    assert result.source == "embedding"
    assert result.confidence >= 0.70


@pytest.mark.asyncio
async def test_llm_classifier_is_used_when_rules_and_embedding_are_uncertain() -> None:
    llm_result = IntentClassification(
        intent="hr:payroll",
        confidence=0.86,
        source="llm",
        reason="question asks about compensation",
    )
    llm_client = FakeLLMClient(llm_result)
    classifier = HybridIntentClassifier(
        Settings(
            _env_file=None,
            intent_classifier_mode="hybrid",
            intent_embedding_confidence_threshold=0.99,
            intent_llm_confidence_threshold=0.70,
        ),
        embedding_client=FakeEmbeddingClient(),
        llm_client=llm_client,
    )

    result = await classifier.classify("Can you explain my monthly compensation?")

    assert result.intent == "hr:payroll"
    assert result.source == "llm"
    assert llm_client.calls == ["Can you explain my monthly compensation?"]


@pytest.mark.asyncio
async def test_classifier_falls_back_to_rag_when_llm_is_unavailable() -> None:
    classifier = HybridIntentClassifier(
        Settings(
            _env_file=None,
            intent_classifier_mode="hybrid",
            intent_embedding_confidence_threshold=0.99,
        ),
        embedding_client=FakeEmbeddingClient(),
        llm_client=FakeLLMClient(error=RuntimeError("unavailable")),
    )

    result = await classifier.classify("Can you explain this unclear internal topic?")

    assert result.intent == "rag"
    assert result.source == "fallback"
    assert result.confidence == 0.0

