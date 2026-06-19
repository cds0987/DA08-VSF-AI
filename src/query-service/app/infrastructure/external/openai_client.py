from collections.abc import AsyncIterator

from fastapi import HTTPException, status

from app.application.ports import SearchResultLike
from app.domain.outcome import Outcome
from app.infrastructure.config import Settings


OUTCOME_GUIDANCE: dict[Outcome, str] = {
    Outcome.NO_INFO: (
        " Neu context khong chua thong tin phu hop, tra loi rang khong tim thay thong tin "
        "trong tai lieu noi bo. Khong du doan hay them thong tin."
    ),
    Outcome.REFUSE: (
        " Tra loi rang nguoi dung khong co quyen truy cap thong tin nay. "
        "Khong cung cap thong tin bi cam."
    ),
    Outcome.CLARIFY: (
        " Neu cau hoi chua ro hoac thieu ngu canh, yeu cau nguoi dung noi ro hon."
    ),
    Outcome.OFF_TOPIC: (
        " Neu cau hoi nam ngoai pham vi HR, chinh sach cong ty, tai lieu noi bo thi tra loi rang cau hoi nam ngoai pham vi ho tro."
    ),
    Outcome.SUCCESS: (
        " Tra loi ngan gon dua tren context, dung tieng Viet."
    ),
}


class OpenAIStreamingClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None
        self._model = settings.openai_llm_model
        if settings.llm_mode == "openai" and settings.openai_api_key:
            from app.infrastructure.external.routed_openai import build_routed_openai, route_model

            # Route qua ai-router (chat.completions, capability `think`) khi OPENAI_BASE_URL set.
            self._client, _ = build_routed_openai(settings)
            self._model = route_model(settings, settings.llm_capability, settings.openai_llm_model)

    async def stream_answer(
        self,
        question: str,
        context: str,
        recent_messages: list[tuple[str, str]],
        sources: list[SearchResultLike],
        is_hr_answer: bool = False,
        outcome: Outcome | None = None,
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
            "Ban la chatbot noi bo VinSmartFuture. Tra loi ngan gon bang tieng Viet, "
            "chi dua tren context duoc cung cap."
        )
        if outcome is not None and outcome in OUTCOME_GUIDANCE:
            system_prompt += OUTCOME_GUIDANCE[outcome]
        if is_hr_answer:
            system_prompt += " Du lieu HR la du lieu ca nhan cua user hien tai; khong suy doan user khac."

        history = "\n".join(f"{role}: {content}" for role, content in recent_messages[-10:])
        user_prompt = (
            f"Lịch sử gần đây:\n{history or '(trống)'}\n\n"
            f"Context:\n{context}\n\n"
            f"Câu hỏi: {question}"
        )

        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
                max_completion_tokens=self._settings.llm_max_output_tokens,
                temperature=0,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    yield delta
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
        sources: list[SearchResultLike],
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


_SUMMARY_SYSTEM = (
    "Bạn tóm tắt hội thoại nội bộ. Gộp các lượt sau (và bản tóm tắt trước nếu có) thành "
    "3-5 câu tiếng Việt, giữ CHỦ ĐỀ và DỮ KIỆN chính (người dùng hỏi gì, đã kết luận gì). "
    "KHÔNG chép nguyên đoạn tài liệu, KHÔNG bịa thêm. Chỉ trả về đoạn tóm tắt, không lời dẫn."
)


def _extractive_fallback(turns: list[tuple[str, str]], prev_summary: str | None) -> str:
    """Tóm tắt thô khi không có LLM (mock / no key / lỗi): nối dòng đầu mỗi lượt gần."""
    parts = [
        content.strip().split("\n", 1)[0][:80]
        for _role, content in turns[-4:]
        if content and content.strip()
    ]
    tail = " | ".join(parts)
    if prev_summary and tail:
        return f"{prev_summary} | {tail}"
    return tail or (prev_summary or "")


class ConversationSummarizer:
    """Tóm tắt các lượt hội thoại CŨ (bị đẩy khỏi window) thành 1 đoạn ngắn, bằng model rẻ
    qua ai-router (capability `summary` -> gpt-4o-mini). Best-effort: lỗi/mock -> extractive."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None
        self._model = settings.openai_llm_model
        if settings.llm_mode == "openai" and settings.openai_api_key:
            from app.infrastructure.external.routed_openai import build_routed_openai, route_model

            self._client, _ = build_routed_openai(settings)
            self._model = route_model(settings, settings.summary_capability, settings.openai_llm_model)

    async def summarize(
        self,
        turns: list[tuple[str, str]],
        prev_summary: str | None = None,
    ) -> str:
        if not turns:
            return prev_summary or ""
        if self._client is None:
            return _extractive_fallback(turns, prev_summary)

        convo = "\n".join(f"{role}: {content}" for role, content in turns)
        prev = f"Bản tóm tắt trước đó:\n{prev_summary}\n\n" if prev_summary else ""
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM},
                    {"role": "user", "content": f"{prev}Các lượt cần gộp vào tóm tắt:\n{convo}"},
                ],
                temperature=0,
                max_completion_tokens=self._settings.summary_max_tokens,
                stream=False,
            )
            out = (response.choices[0].message.content or "").strip()
            return out or (prev_summary or "")
        except Exception:
            return prev_summary or ""
