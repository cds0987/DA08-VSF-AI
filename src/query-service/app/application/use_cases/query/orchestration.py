from collections.abc import AsyncIterator
import hashlib
import logging
import re
from time import perf_counter
import unicodedata
from uuid import uuid4

from app.application.ports import (
    AuthenticatedUser,
    HrQueryResultLike,
    LLMStreamingClient,
    MCPToolClient,
    SearchResultLike,
    SemanticCache,
    ToolDecisionClient,
)
from app.application.tool_decision import ToolDecision, normalize_tool_decision
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.document_access_repository import DocumentAccessRepository
from app.infrastructure.config import Settings


logger = logging.getLogger(__name__)


class QueryOrchestrationUseCase:
    def __init__(
        self,
        settings: Settings,
        conversation_repo: ConversationRepository,
        document_access_repo: DocumentAccessRepository,
        semantic_cache: SemanticCache,
        mcp_client: MCPToolClient,
        openai_client: LLMStreamingClient,
        tool_decision_client: ToolDecisionClient,
    ) -> None:
        self._settings = settings
        self._conversation_repo = conversation_repo
        self._document_access_repo = document_access_repo
        self._semantic_cache = semantic_cache
        self._mcp_client = mcp_client
        self._openai_client = openai_client
        self._tool_decision_client = tool_decision_client

    async def stream(
        self,
        question: str,
        user: AuthenticatedUser,
    ) -> AsyncIterator[dict]:
        started = perf_counter()
        session_id = str(uuid4())
        await self._conversation_repo.save_message(user.id, "user", question)

        context = await self._conversation_repo.get_context(user.id, recent_k=5)
        recent_messages = [(message.role, message.content) for message in context.recent_messages]
        if _is_identity_question(question):
            async for event in self._handle_identity(user.id, session_id, started):
                yield event
            return

        decision = await self._choose_tool(question, recent_messages)
        if decision.tool_name == "hr_query":
            async for event in self._handle_hr(
                question=question,
                user=user,
                intent=str(decision.arguments["intent"]),
                recent_messages=recent_messages,
                session_id=session_id,
                started=started,
            ):
                yield event
            return

        async for event in self._handle_rag(
            question=question,
            user=user,
            recent_messages=recent_messages,
            session_id=session_id,
            started=started,
        ):
            yield event

    async def _choose_tool(
        self,
        question: str,
        recent_messages: list[tuple[str, str]],
    ) -> ToolDecision:
        try:
            available_tools = await self._mcp_client.list_tools()
            raw_decision = await self._tool_decision_client.choose_tool(
                question=question,
                recent_messages=recent_messages,
                available_tools=available_tools,
            )
        except Exception:
            return ToolDecision(tool_name="rag_search", arguments={}, reason="tool decision failed")

        decision = normalize_tool_decision(raw_decision)
        if decision.tool_name not in set(available_tools):
            return ToolDecision(tool_name="rag_search", arguments={}, reason="chosen tool unavailable")
        return decision

    async def _handle_rag(
        self,
        question: str,
        user: AuthenticatedUser,
        recent_messages: list[tuple[str, str]],
        session_id: str,
        started: float,
    ) -> AsyncIterator[dict]:
        allowed_doc_ids = await self._document_access_repo.get_allowed_doc_ids(
            user_id=user.id,
            role=user.role,
            department=user.department,
        )
        if not allowed_doc_ids:
            async for event in self._fallback(user.id, session_id, started):
                yield event
            return

        cache_namespace = _rag_cache_namespace(allowed_doc_ids)
        cached = await self._semantic_cache.get(cache_namespace, question)
        if cached:
            answer, sources = cached
            for token in _word_chunks(answer):
                yield {"token": token}
            await self._save_assistant(user.id, session_id, answer, sources, started)
            yield {"done": True, "sources": sources, "session_id": session_id, "cached": True}
            return

        results = await self._mcp_client.rag_search(
            query=question,
            document_ids=list(allowed_doc_ids),
            top_k=self._settings.rag_result_limit,
        )
        allowed_doc_id_set = set(allowed_doc_ids)
        acl_filtered_results = []
        for result in results:
            if result.document_id not in allowed_doc_id_set:
                logger.warning(
                    "acl_post_filter_violation",
                    extra={
                        "user_id": user.id,
                        "document_id": result.document_id,
                        "chunk_id": result.chunk_id,
                    },
                )
                continue
            acl_filtered_results.append(result)
        if not acl_filtered_results:
            async for event in self._fallback(user.id, session_id, started):
                yield event
            return

        grounded_results = [
            result for result in acl_filtered_results if result.score >= self._settings.rag_score_threshold
        ]
        if not grounded_results:
            async for event in self._fallback(user.id, session_id, started):
                yield event
            return

        sources = [self._source_payload(result) for result in grounded_results]
        context_text = "\n\n".join(
            f"[{index + 1}] {result.document_name} / {result.caption}\n{result.parent_text}"
            for index, result in enumerate(grounded_results)
        )
        answer_parts: list[str] = []
        async for token in _word_stream(
            self._openai_client.stream_answer(
                question=question,
                context=context_text,
                recent_messages=recent_messages,
                sources=grounded_results,
                is_hr_answer=False,
            )
        ):
            answer_parts.append(token)
            yield {"token": token}

        answer = "".join(answer_parts)
        final_sources = [] if _is_fallback_answer(answer) else sources
        if final_sources:
            await self._semantic_cache.put(cache_namespace, question, answer, final_sources)
        await self._save_assistant(user.id, session_id, answer, final_sources, started)
        done_event = {"done": True, "sources": final_sources, "session_id": session_id}
        if not final_sources:
            done_event["fallback"] = True
        yield done_event

    async def _handle_identity(
        self,
        user_id: str,
        session_id: str,
        started: float,
    ) -> AsyncIterator[dict]:
        answer = (
            "Mình là trợ lý nội bộ VinSmartFuture, hỗ trợ trả lời dựa trên tài liệu nội bộ "
            "và dữ liệu bạn được cấp quyền truy cập."
        )
        for token in _word_chunks(answer):
            yield {"token": token}
        await self._save_assistant(user_id, session_id, answer, [], started)
        yield {"done": True, "sources": [], "session_id": session_id}

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
        save_message_detail = getattr(self._conversation_repo, "save_message_detail", None)
        if save_message_detail:
            await save_message_detail(
                user_id=user_id,
                role="assistant",
                content=answer,
                session_id=session_id,
                sources=sources,
                latency_ms=latency_ms,
            )
            context = await self._conversation_repo.get_context(user_id, recent_k=6)
            if (
                self._settings.llm_mode.strip().lower() == "mock"
                and len(context.recent_messages) >= 10
            ):
                summary = _extractive_summary(
                    [(message.role, message.content) for message in context.recent_messages]
                )
                if not summary:
                    return
                await self._conversation_repo.update_summary(
                    user_id,
                    summary,
                )
        else:
            await self._conversation_repo.save_message(user_id, "assistant", answer)

    @staticmethod
    def _source_payload(result: SearchResultLike) -> dict:
        return {
            "document_name": result.document_name,
            "caption": result.caption,
            "heading_path": result.heading_path,
            "score": result.score,
            "source_gcs_uri": result.source_gcs_uri,
        }


def _hr_context_text(result: HrQueryResultLike) -> str:
    if result.summary:
        return result.summary
    return f"Không có dữ liệu HR phù hợp cho intent {result.intent}."


def _extractive_summary(messages: list[tuple[str, str]]) -> str | None:
    snippets = []
    for role, content in messages:
        normalized = " ".join(content.split())
        if not normalized:
            continue
        snippets.append(f"{role}: {normalized[:180]}")
    if not snippets:
        return None
    return "Recent conversation: " + " | ".join(snippets[-6:])


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


def _rag_cache_namespace(document_ids: list[str]) -> str:
    joined = "\n".join(sorted(document_ids))
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return f"rag:{digest}"


def _normalize_text(text: str) -> str:
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(character)
    )
    without_punctuation = re.sub(r"[_\W]+", " ", without_accents, flags=re.UNICODE)
    return re.sub(r"\s+", " ", without_punctuation).strip()


def _is_identity_question(question: str) -> bool:
    normalized = _normalize_text(question)
    phrases = (
        "ban la ai",
        "ban lam duoc gi",
        "ban co the lam gi",
        "gioi thieu ve ban",
        "who are you",
        "what can you do",
    )
    return any(phrase in normalized for phrase in phrases)


def _is_fallback_answer(answer: str) -> bool:
    normalized = _normalize_text(answer)
    return "khong tim thay thong tin trong tai lieu noi bo" in normalized
