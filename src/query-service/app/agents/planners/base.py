"""Planner ABC — biến câu hỏi thành Plan (route + steps DAG). Đăng ký @register_planner."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable

from app.agents.base import RoleSpec
from app.agents.plan_schema import Plan


@dataclass(frozen=True)
class PlanContext:
    """Đầu vào để planner sinh plan."""

    question: str
    role_catalog: tuple[RoleSpec, ...]          # role active (từ manifest) -> catalog
    make_model: Callable[[str], Any] | None     # capability -> chat model (.ainvoke)
    history: list | None = None                 # recent messages (memory)
    emit: Callable[[dict], Any] | None = None    # SSE emit -> stream reasoning lúc lập kế hoạch


class Planner(ABC):
    name: str = ""

    @abstractmethod
    async def plan(self, ctx: PlanContext) -> Plan:
        raise NotImplementedError
