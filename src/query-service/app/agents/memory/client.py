"""InProcessMemoryClient — adapter in-process của MemoryClient port.

COMPOSE (không sở hữu dữ liệu thẩm quyền):
- dialogue: recent N (7) + rolling summary  (lấy qua dialogue_loader = conversation repo)
- task_state + working_set: RedisStmStore (ACL-scope user_id)
- preferences: STUB (Phase sau)
Fail-safe: mọi lỗi -> MemoryContext.empty() (MOSA degrade, KHÔNG vỡ). MEMORY_MODE=mock -> NoOp store.

Tách service sau = viết adapter MemoryClient khác (HTTP), MOSA KHÔNG đổi (contract ổn định).
"""
from __future__ import annotations

import asyncio
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
        # Write-behind: chỉ re-summarize NỀN khi older tăng >= ngưỡng này (tiết kiệm cost gpt-4o-mini
        # + đỡ summarize mỗi turn). Giữ ref task nền để không bị GC giữa chừng.
        self._summary_refresh_every = max(1, recent_n // 2)
        self._bg_tasks: set[asyncio.Task] = set()

    async def load_context(self, user_id: str, conversation_id: str | None, query: str) -> MemoryContext:
        try:
            msgs = await self._load_dialogue(user_id, conversation_id) or []
            recent = msgs[-self._recent_n:]
            summary = ""
            older = msgs[: len(msgs) - len(recent)]
            if len(msgs) > self._summarize_after and older:
                # WRITE-BEHIND: đọc summary cache (TỨC THÌ, không gọi LLM trên hot-path). Nếu chưa có
                # (cold) hoặc older đã tăng đủ ngưỡng -> đặt lịch re-summarize NỀN cho turn sau.
                # Hot-path KHÔNG bao giờ chờ summarize -> cắt 5-16s dead-air. Summary trễ tối đa
                # vài lượt; recent_n verbatim bù phần đó. Cold turn đầu: summary rỗng (chấp nhận).
                cached_sum, cached_n = await self._stm.get_summary(user_id, conversation_id)
                summary = cached_sum or ""
                if cached_sum is None or (len(older) - cached_n) >= self._summary_refresh_every:
                    self._schedule_summary_refresh(user_id, conversation_id, older)
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

    def _schedule_summary_refresh(
        self, user_id: str, conversation_id: str | None, older: list[tuple[str, str]],
    ) -> None:
        """Đặt lịch re-summarize NỀN (fire-and-forget). Giữ ref để task không bị GC; lỗi -> nuốt."""
        try:
            t = asyncio.create_task(self._refresh_summary(user_id, conversation_id, list(older)))
            self._bg_tasks.add(t)
            t.add_done_callback(self._bg_tasks.discard)
        except RuntimeError:  # không có event loop đang chạy (không nên xảy ra ở async path)
            pass

    async def _refresh_summary(
        self, user_id: str, conversation_id: str | None, older: list[tuple[str, str]],
    ) -> None:
        try:
            s = await self._summarize(older)
            if s:
                await self._stm.set_summary(user_id, conversation_id, s, len(older))
        except Exception as exc:  # noqa: BLE001 — refresh nền KHÔNG được làm vỡ gì
            logger.warning("memory_summary_refresh_failed: %s", str(exc)[:160])

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
