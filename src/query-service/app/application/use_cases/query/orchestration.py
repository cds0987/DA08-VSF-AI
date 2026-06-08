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
    RouteDecisionProvider,
    SearchResultLike,
    SemanticCache,
    ToolDecisionClient,
)
from app.application.route_decision import RouteDecision, coerce_route_decision
from app.domain.outcome import Outcome
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
        route_decision_provider: RouteDecisionProvider | ToolDecisionClient | None = None,
        tool_decision_client: ToolDecisionClient | None = None,
    ) -> None:
        self._settings = settings
        self._conversation_repo = conversation_repo
        self._document_access_repo = document_access_repo
        self._semantic_cache = semantic_cache
        self._mcp_client = mcp_client
        self._openai_client = openai_client
        if route_decision_provider is None and tool_decision_client is None:
            raise ValueError("A route decision provider is required")
        self._route_decision_provider = route_decision_provider or tool_decision_client

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
        decision = await self._choose_route(question, recent_messages)

        # Handle direct responses for clarification or out of scope
        if decision.decision in {"clarification", "identity_shortcut", "out_of_scope", "off_topic"}:
            async for event in self._handle_direct_response(
                user.id,
                session_id,
                started,
                str(decision.direct_response or ""),
                decision.outcome,
            ):
                yield event
            return

        # If the routing decision indicates a non-success outcome, use fallback with appropriate message
        from app.domain.outcome import Outcome
        if decision.outcome != Outcome.SUCCESS:
            async for event in self._fallback(
                user.id, session_id, started, decision.outcome,
                question=question, recent_messages=recent_messages,
            ):
                yield event
            return

        if decision.decision == "hr_query" and self._settings.tool_routing_mode.strip().lower() == "legacy":
            async for event in self._handle_hr(
                question=question,
                user=user,
                intent=str(decision.tool_arguments["intent"]),
                recent_messages=recent_messages,
                session_id=session_id,
                started=started,
                outcome=decision.outcome,
            ):
                yield event
            return

        if decision.decision != "rag_search":
            async for event in self._handle_generic_tool(
                question=question,
                tool_name=decision.decision,
                arguments=dict(decision.tool_arguments),
                user=user,
                recent_messages=recent_messages,
                session_id=session_id,
                started=started,
                outcome=decision.outcome,
            ):
                yield event
            return

        async for event in self._handle_rag(
            question=question,
            search_query=str(decision.tool_arguments.get("query") or question),
            user=user,
            recent_messages=recent_messages,
            session_id=session_id,
            started=started,
            outcome=decision.outcome,
        ):
            yield event

    async def _choose_route(
        self,
        question: str,
        recent_messages: list[tuple[str, str]],
    ) -> RouteDecision:
        try:
            available_tools = await self._mcp_client.list_tools()
            choose_route = getattr(self._route_decision_provider, "choose_route", None)
            if choose_route is not None:
                raw_decision = await choose_route(
                    question=question,
                    recent_messages=recent_messages,
                    available_tools=available_tools,
                )
            else:
                raw_decision = await self._route_decision_provider.choose_tool(
                    question=question,
                    recent_messages=recent_messages,
                    available_tools=available_tools,
                )
        except Exception:
            return RouteDecision(
                decision="rag_search",
                tool_arguments={"query": question},
                reason="route decision failed",
                confidence=0.0,
            )

        return coerce_route_decision(
            raw_decision,
            default_query=question,
            allow_generic_tools=self._settings.tool_routing_mode.strip().lower() == "native",
        )

    async def _handle_rag(
        self,
        question: str,
        search_query: str,
        user: AuthenticatedUser,
        recent_messages: list[tuple[str, str]],
        session_id: str,
        started: float,
        outcome: Outcome,
    ) -> AsyncIterator[dict]:
        allowed_doc_ids = await self._document_access_repo.get_allowed_doc_ids(
            user_id=user.id,
            role=user.role,
            department=user.department,
        )
        if not allowed_doc_ids:
            async for event in self._fallback(
                user.id, session_id, started, Outcome.NO_INFO,
                question=question, recent_messages=recent_messages,
            ):
                yield event
            return

        cache_namespace = _rag_cache_namespace(allowed_doc_ids)
        cached = await self._semantic_cache.get(cache_namespace, question)
        if cached:
            answer, sources = cached
            for token in _word_chunks(answer):
                yield {"token": token}
            await self._save_assistant(user.id, session_id, answer, sources, started)
            yield {"done": True, "sources": sources, "session_id": session_id, "cached": True, "outcome": outcome.value}
            return

        results = await self._mcp_client.rag_search(
            query=search_query,
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
            async for event in self._fallback(
                user.id, session_id, started, Outcome.NO_INFO,
                question=question, recent_messages=recent_messages,
            ):
                yield event
            return

        grounded_results = [
            result for result in acl_filtered_results if result.score >= self._settings.rag_score_threshold
        ]
        if not grounded_results:
            async for event in self._fallback(
                user.id, session_id, started, Outcome.NO_INFO,
                question=question, recent_messages=recent_messages,
            ):
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
                outcome=Outcome.SUCCESS,
            )
        ):
            answer_parts.append(token)
            yield {"token": token}

        answer = "".join(answer_parts)
        final_sources = [] if _is_fallback_answer(answer) else sources
        if final_sources:
            await self._semantic_cache.put(cache_namespace, question, answer, final_sources)
        await self._save_assistant(user.id, session_id, answer, final_sources, started)
        done_event = {
            "done": True,
            "sources": final_sources,
            "session_id": session_id,
            "outcome": outcome.value,
        }
        if not final_sources:
            done_event["fallback"] = True
        yield done_event

    async def _handle_direct_response(
        self,
        user_id: str,
        session_id: str,
        started: float,
        answer: str,
        outcome: Outcome,
    ) -> AsyncIterator[dict]:
        for token in _word_chunks(answer):
            yield {"token": token}
        await self._save_assistant(user_id, session_id, answer, [], started)
        yield {"done": True, "sources": [], "session_id": session_id, "outcome": outcome.value}

    async def _handle_hr(
        self,
        question: str,
        user: AuthenticatedUser,
        intent: str,
        recent_messages: list[tuple[str, str]],
        session_id: str,
        started: float,
        outcome: Outcome,
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
                outcome=Outcome.SUCCESS,
            )
        ):
            answer_parts.append(token)
            yield {"token": token}

        answer = "".join(answer_parts)
        await self._save_assistant(user.id, session_id, answer, [], started)
        yield {"done": True, "sources": [], "session_id": session_id, "outcome": outcome.value}

    async def _handle_generic_tool(
        self,
        question: str,
        tool_name: str,
        arguments: dict,
        user: AuthenticatedUser,
        recent_messages: list[tuple[str, str]],
        session_id: str,
        started: float,
        outcome: Outcome,
    ) -> AsyncIterator[dict]:
        tool_result = await self._mcp_client.call_tool(
            tool_name,
            await self._inject_reserved_arguments(tool_name=tool_name, arguments=arguments, user=user),
        )
        context_text = str(tool_result.get("summary") or "")
        if not context_text:
            context_text = f"Khong co du lieu phu hop tu tool {tool_name}."
        answer_parts: list[str] = []
        async for token in _word_stream(
            self._openai_client.stream_answer(
                question=question,
                context=context_text,
                recent_messages=recent_messages,
                sources=[],
                is_hr_answer=tool_name == "hr_query",
                outcome=Outcome.SUCCESS,
            )
        ):
            answer_parts.append(token)
            yield {"token": token}

        answer = "".join(answer_parts)
        await self._save_assistant(user.id, session_id, answer, [], started)
        yield {"done": True, "sources": [], "session_id": session_id, "outcome": outcome.value}

    async def _inject_reserved_arguments(
        self,
        *,
        tool_name: str,
        arguments: dict,
        user: AuthenticatedUser,
    ) -> dict:
        payload = dict(arguments)
        payload.pop("user_id", None)
        payload.pop("document_ids", None)
        payload.pop("top_k", None)

        if tool_name == "rag_search":
            allowed_doc_ids = await self._document_access_repo.get_allowed_doc_ids(
                user_id=user.id,
                role=user.role,
                department=user.department,
            )
            payload["document_ids"] = list(allowed_doc_ids)
            payload["top_k"] = self._settings.rag_result_limit
            return payload

        if tool_name == "hr_query":
            payload["user_id"] = user.id
            return payload

        spec_by_name = {
            spec.name: spec
            for spec in await self._mcp_client.list_tool_specs()
        }
        schema = spec_by_name.get(tool_name)
        if schema is None:
            return payload
        properties = schema.input_schema.get("properties") or {}
        if "user_id" in properties:
            payload["user_id"] = user.id
        if "document_ids" in properties:
            allowed_doc_ids = await self._document_access_repo.get_allowed_doc_ids(
                user_id=user.id,
                role=user.role,
                department=user.department,
            )
            payload["document_ids"] = list(allowed_doc_ids)
        if "top_k" in properties:
            payload["top_k"] = self._settings.rag_result_limit
        return payload

    async def _fallback(
        self,
        user_id: str,
        session_id: str,
        started: float,
        outcome: Outcome,
        question: str = "",
        recent_messages: list[tuple[str, str]] | None = None,
    ) -> AsyncIterator[dict]:
        messages = {
            Outcome.NO_INFO: "Không tìm thấy thông tin trong tài liệu nội bộ",
            Outcome.REFUSE: "Bạn không có đủ quyền hạn truy cập thông tin này",
            Outcome.CLARIFY: "Tôi chưa hiểu ý bạn, bạn có thể đưa thêm thông tin được không",
            Outcome.OFF_TOPIC: "Câu hỏi của bạn nằm ngoài phạm vi hệ thống HR và tài liệu nội bộ. "
                              "Tôi chỉ hỗ trợ về chính sách công ty, HR và thông tin nội bộ.",
        }
        static_message = messages.get(outcome, "Không tìm thấy thông tin trong tài liệu nội bộ")

        # Neu co conversation context, thu dung LLM de generate tra loi co ngu canh
        if recent_messages and outcome == Outcome.NO_INFO:
            context_lines = "\n".join(
                f"{role}: {content}" for role, content in recent_messages[-6:]
            )
            context_for_llm = (
                f"Lich su cuoi cung:\n{context_lines}\n\n"
                f"Cau hoi hien tai: {question}\n\n"
                f"Tra loi ngan gon, dua tren ngu canh o tren, "
                f"neu cau hoi hien tai la follow-up thi noi ro hon."
            )
            try:
                answer_parts: list[str] = []
                async for token in _word_stream(
                    self._openai_client.stream_answer(
                        question=question,
                        context=context_for_llm,
                        recent_messages=recent_messages,
                        sources=[],
                        is_hr_answer=False,
                        outcome=outcome,
                    )
                ):
                    answer_parts.append(token)
                    yield {"token": token}
                answer = "".join(answer_parts)
                await self._save_assistant(user_id, session_id, answer, [], started)
                yield {"done": True, "sources": [], "session_id": session_id, "fallback": True}
                return
            except Exception:
                # LLM failed, fall through to static message
                pass

        for token in _word_chunks(static_message):
            yield {"token": token}
        await self._save_assistant(user_id, session_id, static_message, [], started)
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
                await self._conversation_repo.update_summary(user_id, summary)
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
    return f"Khong co du lieu HR phu hop cho intent {result.intent}."


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


def _is_fallback_answer(answer: str) -> bool:
    normalized = _normalize_text(answer)
    return "khong tim thay thong tin trong tai lieu noi bo" in normalized
