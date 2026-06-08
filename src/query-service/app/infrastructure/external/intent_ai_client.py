from __future__ import annotations

from collections.abc import Sequence
import hashlib
import json
import re
import unicodedata

from app.application.intent_classifier import IntentClassification, VALID_INTENTS
from app.infrastructure.config import Settings


STOPWORDS = {
    "a",
    "ai",
    "an",
    "and",
    "are",
    "ban",
    "can",
    "co",
    "cua",
    "do",
    "duoc",
    "gi",
    "have",
    "how",
    "i",
    "is",
    "la",
    "much",
    "my",
    "still",
    "the",
    "toi",
    "ve",
    "what",
    "who",
    "you",
}


class TokenHashIntentEmbeddingClient:
    def __init__(self, dimensions: int = 128) -> None:
        self._dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            vector[index] += 1.0
        return vector


class OpenAIIntentEmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI intent embeddings")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_seconds,
        )
        self._model = settings.openai_embedding_model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        return [list(item.embedding) for item in response.data]


class OpenAIIntentLLMClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI intent classification")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.intent_llm_timeout_seconds,
        )
        self._model = settings.intent_llm_model

    async def classify(
        self,
        question: str,
        recent_messages: Sequence[tuple[str, str]] | None = None,
    ) -> IntentClassification:
        history = "\n".join(
            f"{role}: {content}" for role, content in list(recent_messages or [])[-5:]
        )
        response = await self._client.responses.create(
            model=self._model,
            instructions=(
                "Classify one user question for an internal company chatbot. "
                "Return only JSON with fields: intent, confidence, reason. "
                f"Allowed intent values: {', '.join(sorted(VALID_INTENTS))}. "
                "Use the same intent for semantically equivalent English and Vietnamese questions. "
                "Use identity for questions about who the assistant is or who created it. "
                "Use clarification for greetings, vague chat, or low-context follow-ups that should ask the user to clarify. "
                "Use out_of_scope for passwords, credentials, internal secrets, or unsafe requests. "
                "Use hr:leave_balance, hr:leave_requests, or hr:payroll only for the current user's personal HR data. "
                "Use rag for policies, procedures, onboarding, guidelines, and internal document lookup. "
                "Do not include user_id, document_ids, tool arguments, or direct responses."
            ),
            input=(
                f"Recent messages:\n{history or '(empty)'}\n\n"
                f"Question:\n{question}"
            ),
        )
        payload = json.loads(getattr(response, "output_text", "") or "{}")
        return IntentClassification(
            intent=str(payload.get("intent", "")),
            confidence=float(payload.get("confidence", 0.0)),
            source="llm",
            reason=str(payload.get("reason", "")),
        )


def _tokens(text: str) -> list[str]:
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(character)
    )
    return [
        token
        for token in re.findall(r"\w+", normalized)
        if len(token) > 1 and token not in STOPWORDS
    ]
