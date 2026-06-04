from collections.abc import AsyncIterator

from fastapi import HTTPException, status

from app.infrastructure.config import Settings
from app.infrastructure.external.mcp_client import SearchResult


class OpenAIStreamingClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None
        if settings.llm_mode == "openai" and settings.openai_api_key:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                timeout=settings.openai_timeout_seconds,
            )

    async def stream_answer(
        self,
        question: str,
        context: str,
        recent_messages: list[tuple[str, str]],
        sources: list[SearchResult],
        is_hr_answer: bool = False,
    ) -> AsyncIterator[str]:
        if self._settings.llm_mode == "mock":
            async for chunk in self._mock_stream(question, context, sources, is_hr_answer):
                yield chunk
            return

        if self._client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OPENAI_API_KEY is required when LLM_MODE=openai",
            )

        system_prompt = (
            "Bạn là chatbot nội bộ VinSmartFuture. Trả lời ngắn gọn bằng tiếng Việt, "
            "chỉ dựa trên context được cung cấp. Nếu context không đủ, nói không tìm thấy "
            "thông tin trong tài liệu nội bộ."
        )
        if is_hr_answer:
            system_prompt += " Dữ liệu HR là dữ liệu cá nhân của user hiện tại; không suy đoán user khác."

        history = "\n".join(f"{role}: {content}" for role, content in recent_messages[-10:])
        user_prompt = (
            f"Lịch sử gần đây:\n{history or '(trống)'}\n\n"
            f"Context:\n{context}\n\n"
            f"Câu hỏi: {question}"
        )

        try:
            stream = await self._client.responses.create(
                model=self._settings.openai_llm_model,
                instructions=system_prompt,
                input=user_prompt,
                stream=True,
            )
            async for event in stream:
                if getattr(event, "type", None) == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield delta
                elif getattr(event, "type", None) == "error":
                    raise RuntimeError(str(getattr(event, "error", "OpenAI streaming error")))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"OpenAI unavailable: {exc}",
            ) from exc

    async def _mock_stream(
        self,
        question: str,
        context: str,
        sources: list[SearchResult],
        is_hr_answer: bool,
    ) -> AsyncIterator[str]:
        if is_hr_answer:
            answer = f"Dữ liệu HR mock cho câu hỏi '{question}': {context}"
        else:
            source_name = sources[0].document_name if sources else "mock data"
            answer = (
                f"Theo {source_name}, {context.splitlines()[0] if context else 'chưa có context phù hợp'}"
            )
        for part in _chunk_text(answer):
            yield part


def _chunk_text(text: str, size: int = 24) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]
