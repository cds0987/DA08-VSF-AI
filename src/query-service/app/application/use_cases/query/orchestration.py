from collections.abc import AsyncIterator
from time import perf_counter
from uuid import uuid4
import re

from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.document_access_repository import DocumentAccessRepository
from app.infrastructure.auth.auth_service import AuthenticatedUser
from app.infrastructure.cache.semantic_cache import InMemorySemanticCache
from app.infrastructure.config import Settings
from app.infrastructure.db.mock_conversation_repo import InMemoryConversationRepository
from app.infrastructure.external.mcp_client import HrQueryResult, MockMCPClient, SearchResult
from app.infrastructure.external.openai_client import OpenAIStreamingClient


class QueryOrchestrationUseCase:
    def __init__(
        self,
        settings: Settings,
        conversation_repo: ConversationRepository,
        document_access_repo: DocumentAccessRepository,
        semantic_cache: InMemorySemanticCache,
        mcp_client: MockMCPClient,
        openai_client: OpenAIStreamingClient,
    ) -> None:
        self._settings = settings
        self._conversation_repo = conversation_repo
        self._document_access_repo = document_access_repo
        self._semantic_cache = semantic_cache
        self._mcp_client = mcp_client
        self._openai_client = openai_client

    async def stream(
        self,
        question: str,
        user: AuthenticatedUser,
    ) -> AsyncIterator[dict]:
        started = perf_counter()
        session_id = str(uuid4())
        await self._conversation_repo.save_message(user.id, "user", question)

        cached = await self._semantic_cache.get(question)
        if cached:
            answer, sources = cached
            for token in _word_chunks(answer):
                yield {"token": token}
            await self._save_assistant(user.id, session_id, answer, sources, started)
            yield {"done": True, "sources": sources, "session_id": session_id, "cached": True}
            return

        context = await self._conversation_repo.get_context(user.id, recent_k=5)
        recent_messages = [(message.role, message.content) for message in context.recent_messages]
        intent = self._detect_intent(question)
        if intent.startswith("hr:"):
            async for event in self._handle_hr(
                question=question,
                user=user,
                intent=intent.removeprefix("hr:"),
                recent_messages=recent_messages,
                session_id=session_id,
                started=started,
            ):
                yield event
            return

        allowed_doc_ids = await self._document_access_repo.get_allowed_doc_ids(
            user_id=user.id,
            role=user.role,
            department=user.department,
        )
        if not allowed_doc_ids:
            async for event in self._fallback(user.id, session_id, started):
                yield event
            return

        results = await self._mcp_client.rag_search(
            query=question,
            document_ids=list(allowed_doc_ids),
            top_k=5,
        )
        if not results or max(result.score for result in results) < self._settings.rag_score_threshold:
            async for event in self._fallback(user.id, session_id, started):
                yield event
            return

        sources = [self._source_payload(result) for result in results[:3]]
        context_text = "\n\n".join(
            f"[{index + 1}] {result.document_name} / {result.caption}\n{result.parent_text}"
            for index, result in enumerate(results[:3])
        )
        answer_parts: list[str] = []
        async for token in _word_stream(
            self._openai_client.stream_answer(
                question=question,
                context=context_text,
                recent_messages=recent_messages,
                sources=results[:3],
                is_hr_answer=False,
            )
        ):
            answer_parts.append(token)
            yield {"token": token}

        answer = "".join(answer_parts)
        await self._semantic_cache.put(question, answer, sources)
        await self._save_assistant(user.id, session_id, answer, sources, started)
        yield {"done": True, "sources": sources, "session_id": session_id}

    async def _handle_hr(
        self,
        question: str,
        user: AuthenticatedUser,
        intent: str,
        recent_messages: list[tuple[str, str]],
        session_id: str,
        started: float,
    ) -> AsyncIterator[dict]:
        tool_result = await self._mcp_client.hr_query(user_id=user.id, intent=intent)
        context_text = _hr_context_text(tool_result)
        answer_parts: list[str] = []
        async for token in _word_stream(
            self._openai_client.stream_answer(
                question=question,
                context=context_text,
                recent_messages=recent_messages,
                sources=[],
                is_hr_answer=True,
            )
        ):
            answer_parts.append(token)
            yield {"token": token}

        answer = "".join(answer_parts)
        await self._save_assistant(user.id, session_id, answer, [], started)
        yield {"done": True, "sources": [], "session_id": session_id}

    async def _fallback(
        self,
        user_id: str,
        session_id: str,
        started: float,
    ) -> AsyncIterator[dict]:
        answer = "Không tìm thấy thông tin trong tài liệu nội bộ."
        for token in _word_chunks(answer):
            yield {"token": token}
        await self._save_assistant(user_id, session_id, answer, [], started)
        yield {"done": True, "sources": [], "session_id": session_id, "fallback": True}

    async def _save_assistant(
        self,
        user_id: str,
        session_id: str,
        answer: str,
        sources: list[dict],
        started: float,
    ) -> None:
        latency_ms = int((perf_counter() - started) * 1000)
        if isinstance(self._conversation_repo, InMemoryConversationRepository):
            await self._conversation_repo.save_message_detail(
                user_id=user_id,
                role="assistant",
                content=answer,
                session_id=session_id,
                sources=sources,
                latency_ms=latency_ms,
            )
            context = await self._conversation_repo.get_context(user_id, recent_k=6)
            if len(context.recent_messages) >= 10:
                await self._conversation_repo.update_summary(
                    user_id,
                    "Tóm tắt mock: người dùng đang trao đổi về chính sách nội bộ/HR.",
                )
        else:
            await self._conversation_repo.save_message(user_id, "assistant", answer)

    @staticmethod
    def _source_payload(result: SearchResult) -> dict:
        return {
            "document_name": result.document_name,
            "caption": result.caption,
            "heading_path": result.heading_path,
            "score": result.score,
            "source_s3_uri": result.source_s3_uri,
        }

    @staticmethod
    def _detect_intent(question: str) -> str:
        lower = question.lower()
        if any(keyword in lower for keyword in ["lương", "payroll", "khấu trừ"]):
            return "hr:payroll"
        if any(keyword in lower for keyword in ["đơn nghỉ", "leave request", "trạng thái nghỉ"]):
            return "hr:leave_requests"
        if any(keyword in lower for keyword in ["ngày nghỉ", "nghỉ phép còn", "leave balance"]):
            return "hr:leave_balance"
        return "rag"


def _hr_context_text(result: HrQueryResult) -> str:
    if result.summary:
        return result.summary
    return f"Không có dữ liệu HR phù hợp cho intent {result.intent}."


def _word_chunks(text: str) -> list[str]:
    return re.findall(r"\S+\s*", text) or [""]


async def _word_stream(chunks: AsyncIterator[str]) -> AsyncIterator[str]:
    buffer = ""
    async for chunk in chunks:
        buffer += chunk
        while True:
            match = re.match(r"(\S+\s+)", buffer)
            if not match:
                break
            token = match.group(1)
            buffer = buffer[len(token) :]
            yield token
    if buffer:
        yield buffer
