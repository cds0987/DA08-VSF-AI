"""InProcessMemoryClient — adapter in-process của MemoryClient port.

COMPOSE (không sở hữu dữ liệu thẩm quyền):
- dialogue: recent N (7) + rolling summary  (lấy qua dialogue_loader = conversation repo)
- task_state + working_set: RedisStmStore (ACL-scope user_id)
- preferences: STUB (Phase sau)
Fail-safe: mọi lỗi -> MemoryContext.empty() (MOSA degrade, KHÔNG vỡ). MEMORY_MODE=mock -> NoOp store.

Tách service sau = viết adapter MemoryClient khác (HTTP), MOSA KHÔNG đổi (contract ổn định).
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from app.agents.memory.contracts import (
    MemoryContext, Pref, TaskState, Turn, WorkingSetDigest, WorkingSetItem,
)
from app.agents.roles._llm import acomplete

logger = logging.getLogger(__name__)

# loader: async (user_id, conversation_id) -> list[(role, content)] thô gần nhất.
DialogueLoader = Callable[[str, str | None], Awaitable[list[tuple[str, str]]]]


class InProcessMemoryClient:
    def __init__(
        self,
        *,
        stm_store: Any,                       # RedisStmStore | NoOpStmStore
        dialogue_loader: DialogueLoader,
        make_model: Callable[[str], Any] | None = None,
        recent_n: int = 7,                    # giữ 7 lượt gần verbatim (hot-config)
        summarize_after: int = 12,            # >12 lượt -> nén phần cũ thành summary
    ) -> None:
        self._stm = stm_store
        self._load_dialogue = dialogue_loader
        self._make_model = make_model
        self._recent_n = max(1, recent_n)
        self._summarize_after = summarize_after

    async def load_context(self, user_id: str, conversation_id: str | None, query: str) -> MemoryContext:
        try:
            msgs = await self._load_dialogue(user_id, conversation_id) or []
            recent = msgs[-self._recent_n:]
            summary = ""
            older = msgs[: len(msgs) - len(recent)]
            if len(msgs) > self._summarize_after and older:
                summary = await self._summarize(older)
            task = await self._stm.get_task(user_id, conversation_id)
            ws = await self._stm.get_ws(user_id, conversation_id)
            prefs: tuple[Pref, ...] = ()  # STUB Phase sau (LTM)
            return MemoryContext(
                dialogue=tuple(Turn(role=r, content=c) for r, c in recent),
                summary=summary, task_state=task, working_set=ws, preferences=prefs,
            )
        except Exception as exc:  # noqa: BLE001 — fail-safe: memory KHÔNG được làm vỡ query
            logger.warning("memory_load_context_failed: %s", str(exc)[:160])
            return MemoryContext.empty()

    async def record_turn(self, user_id, conversation_id, role, content, meta=None) -> None:
        # Dialogue được conversation repo lưu (luồng hiện tại). Hook consolidation/preference
        # learning ở Phase sau. Hiện no-op (best-effort).
        return None

    async def get_task_state(self, user_id, conversation_id) -> TaskState | None:
        try:
            return await self._stm.get_task(user_id, conversation_id)
        except Exception:  # noqa: BLE001
            return None

    async def set_task_state(self, user_id, conversation_id, state) -> None:
        try:
            await self._stm.set_task(user_id, conversation_id, state)
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_set_task_failed: %s", str(exc)[:120])

    async def add_evidence(self, user_id, conversation_id, item: WorkingSetItem) -> None:
        try:
            await self._stm.add_evidence(user_id, conversation_id, item)
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_add_evidence_failed: %s", str(exc)[:120])

    async def _summarize(self, older: list[tuple[str, str]]) -> str:
        model = self._make_model("summary") if self._make_model else None
        if model is None:
            return ""
        convo = "\n".join(f"{r}: {c}" for r, c in older)
        s = await acomplete(
            model,
            system="Tóm tắt hội thoại thành sự thật/ngữ cảnh quan trọng cho lượt sau. Ngắn gọn, gạch đầu dòng.",
            user=convo,
        )
        return (s or "").strip()
