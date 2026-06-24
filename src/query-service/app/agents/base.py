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
    # solo: True = step dữ liệu DUY NHẤT của plan -> worker có thể BỎ bước distill thừa
    # (verify_answer tự synth trên data thô). Set bởi graph_builder khi plan chỉ 1 step.
    solo: bool = False


@dataclass(frozen=True)
class WorkerOutput:
    """Kết quả 1 worker. status=error vẫn hợp lệ -> synthesize chạy với phần còn lại."""

    step_id: int
    role: str
    output: Any
    sources: list[dict[str, Any]] = field(default_factory=list)
    status: WorkerStatus = "ok"
    error: str | None = None
    # retrieved: số chunk rag LẤY ĐƯỢC (kể cả dưới ngưỡng citation). Tách "pipeline khỏe"
    # (retrieved>0: embed+qdrant+search chạy) khỏi "citation" (sources: chunk >= threshold).
    retrieved: int = 0


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
    hint_doc_ids: tuple[str, ...] = ()
    rag_top_k: int = 5
    rag_score_threshold: float = 0.45
    make_model: Callable[[str], Any] | None = None
    # emit(ev: dict) -> đẩy progress event ra SSE (Suy nghĩ / bước tool / token answer).
    # None (test/non-stream) -> role bỏ qua emit. Set bởi _stream_orchestrator mỗi request.
    emit: Callable[[dict], Any] | None = None
    # history: hội thoại gần đây (role, content) — role cần để CARRY-FORWARD (vd sửa ngày/loại
    # đơn nghỉ ở lượt sau). Rỗng cho phần lớn role; leave_action dùng. Set bởi _stream_orchestrator.
    history: tuple[tuple[str, str], ...] = ()
    # tracer + trace: LangfuseTracer + trace handle của lượt query. Role/node dùng để ghi
    # generation (model/token/cost) + span tool MỖI BƯỚC -> trace MOSA có cây bước (không phẳng).
    # None (test/langfuse tắt) -> bỏ qua, best-effort. Set bởi _stream_orchestrator.
    tracer: Any = None
    trace: Any = None


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
