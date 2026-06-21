"""Memory contracts — bề mặt ỔN ĐỊNH (ports & adapters). MOSA CHỈ phụ thuộc cái này,
KHÔNG phụ thuộc cài đặt -> mở rộng/sửa adapter KHÔNG đụng code khác.

Tách 2 concern:
- STM (per conversation): dialogue (7 recent + rolling summary), task_state, working_set.
- LTM (per user): preferences.
Dữ liệu THẨM QUYỀN (HR profile/số phép, RAG docs) KHÔNG lưu ở đây — query tươi qua tool.

GATE (test_memory_architecture_enforcement) ép: worker stateless (không chạm memory),
boundary (chỉ orchestration gọi), shape không drift, token-bound, fail-safe, ACL scope user_id.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Turn:
    role: str
    content: str


@dataclass(frozen=True)
class TaskState:
    """Flow đang dở (vd tạo đơn nghỉ chờ làm rõ loại). Structured -> route TẤT ĐỊNH + nhắc user."""
    flow: str                            # "create_leave" | "approve_leave" | ...
    data: dict[str, Any] = field(default_factory=dict)   # {dates, type, reason...}
    missing: tuple[str, ...] = ()        # field còn thiếu để hoàn tất
    status: str = "pending"              # pending | done | cancelled
    updated_ts: float = 0.0              # để phát hiện task "nguội" -> proactive nhắc


@dataclass(frozen=True)
class WorkingSetItem:
    kind: str                            # "rag" | "hr"
    label: str                           # mô tả ngắn ("chính sách phép năm")
    detail: dict[str, Any] = field(default_factory=dict)  # query/intent/doc names (digest, KHÔNG full)


@dataclass(frozen=True)
class WorkingSetDigest:
    """DIGEST bằng chứng đã lấy phiên này -> cho PLANNER quyết reuse vs delta.
    Worker KHÔNG đọc cái này (worker stateless); chỉ planner/orchestration dùng."""
    items: tuple[WorkingSetItem, ...] = ()


@dataclass(frozen=True)
class Pref:
    key: str
    value: str


@dataclass(frozen=True)
class MemoryContext:
    """Gói context GỌN (token-bounded) bơm vào MOSA đầu lượt. shape ỔN ĐỊNH (drift gate)."""
    dialogue: tuple[Turn, ...] = ()      # ≤ recent N (7)
    summary: str = ""                    # rolling summary lượt cũ
    task_state: TaskState | None = None
    working_set: WorkingSetDigest = field(default_factory=WorkingSetDigest)
    preferences: tuple[Pref, ...] = ()   # top-K LTM

    @staticmethod
    def empty() -> "MemoryContext":
        """Fail-safe: memory lỗi -> context rỗng (MOSA degrade, KHÔNG vỡ)."""
        return MemoryContext()


@runtime_checkable
class MemoryClient(Protocol):
    """PORT memory (peer McpClient). MOSA gọi ở 2 RANH GIỚI: load đầu lượt, record cuối lượt.
    MỌI method scope theo user_id (ACL — KHÔNG rò chéo user)."""

    async def load_context(self, user_id: str, conversation_id: str | None, query: str) -> MemoryContext:
        ...

    async def record_turn(self, user_id: str, conversation_id: str | None,
                          role: str, content: str, meta: dict[str, Any] | None = None) -> None:
        ...

    async def get_task_state(self, user_id: str, conversation_id: str | None) -> TaskState | None:
        ...

    async def set_task_state(self, user_id: str, conversation_id: str | None,
                             state: TaskState | None) -> None:
        ...

    async def add_evidence(self, user_id: str, conversation_id: str | None,
                           item: WorkingSetItem) -> None:
        ...
