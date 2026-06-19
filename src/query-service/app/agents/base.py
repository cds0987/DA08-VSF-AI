"""Hợp đồng I/O của role-agent + lớp cơ sở AgentRole.

WorkerInput/WorkerOutput là message contract giữa orchestrator <-> worker (bus).
bus.py (milestone 2) sẽ thêm reducer merge các WorkerOutput theo step_id.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

WorkerStatus = Literal["ok", "no_info", "error"]


@dataclass(frozen=True)
class WorkerInput:
    """Đầu vào 1 worker cho 1 step của plan."""

    step_id: int
    role: str
    # input: chuỗi query (rag) hoặc dict tham số (vd {"intent": "leave_balance"}).
    input: Any
    direction: str = ""
    # upstream: output các step mà step này depends_on (dep_id -> output).
    upstream: dict[int, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerOutput:
    """Kết quả 1 worker. status=error vẫn hợp lệ -> synthesize chạy với phần còn lại."""

    step_id: int
    role: str
    output: Any
    sources: list[dict[str, Any]] = field(default_factory=list)
    status: WorkerStatus = "ok"
    error: str | None = None


@dataclass(frozen=True)
class RoleSpec:
    """Metadata khai báo của 1 role (đọc từ agents.yaml, ghép vào catalog orchestrator)."""

    name: str
    capability: str
    tools: tuple[str, ...] = ()
    enabled: bool = True
    description: str = ""


@dataclass
class RoleContext:
    """Deps inject cho role-agent mỗi request (ACL + client + model factory).

    make_model(capability) -> chat model có .ainvoke(messages) (langchain BaseChatModel).
    None -> role bỏ qua bước LLM, trả dữ liệu thô (an toàn khi mini không khả dụng / test).
    """

    mcp_client: Any
    user_id: str
    allowed_doc_ids: tuple[str, ...] = ()
    rag_top_k: int = 5
    rag_score_threshold: float = 0.45
    make_model: Callable[[str], Any] | None = None


class AgentRole(ABC):
    """Lớp cơ sở mọi role-agent. Đăng ký bằng @register_agent("ten").

    name:        tên role (= khóa trong registry + agents.yaml).
    capability:  capability gửi ai-router (worker | answer | think ...).
    tools:       tool MCP role được phép gọi (mặc định từ agents.yaml override).
    """

    name: str = ""
    capability: str = "worker"
    tools: tuple[str, ...] = ()

    def __init__(self, ctx: RoleContext) -> None:
        self.ctx = ctx

    @abstractmethod
    async def run(self, task: WorkerInput) -> WorkerOutput:
        """Thực thi 1 step. KHÔNG raise — lỗi -> WorkerOutput(status='error')."""
        raise NotImplementedError

    def describe(self) -> str:
        """Mô tả ngắn cho catalog orchestrator (override để chi tiết hơn)."""
        doc = (self.__doc__ or "").strip().splitlines()
        return doc[0] if doc else self.name
