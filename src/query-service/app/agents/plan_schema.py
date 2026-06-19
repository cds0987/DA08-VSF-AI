"""Plan schema — output có cấu trúc của orchestrator (router=deepseek-pro).

Dùng pydantic v2: vừa validate (retry khi LLM trả sai) vừa sinh JSON Schema cho
structured output. route=light -> trả lời thẳng; route=heavy -> steps + DAG.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class PlanStep(BaseModel):
    id: int = Field(..., ge=1, description="ID step, duy nhất trong plan")
    role: str = Field(..., description="Tên role (phải có trong Agent Registry)")
    input: Any = Field(default="", description="Query (rag) hoặc dict tham số (hr)")
    direction: str = Field(default="", description="Định hướng cụ thể cho worker")
    depends_on: list[int] = Field(default_factory=list, description="ID các step phụ thuộc")


class Plan(BaseModel):
    route: Literal["light", "heavy"]
    answer_hint: str = Field(default="", description="Gợi ý trả lời khi route=light")
    steps: list[PlanStep] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "Plan":
        if self.route == "heavy" and not self.steps:
            raise ValueError("route=heavy phải có ít nhất 1 step")
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step id trùng nhau")
        idset = set(ids)
        for s in self.steps:
            for dep in s.depends_on:
                if dep not in idset:
                    raise ValueError(f"step {s.id} depends_on {dep} không tồn tại")
                if dep == s.id:
                    raise ValueError(f"step {s.id} depends_on chính nó")
        if self._has_cycle():
            raise ValueError("DAG có chu trình")
        return self

    def _has_cycle(self) -> bool:
        deps = {s.id: set(s.depends_on) for s in self.steps}
        seen: set[int] = set()
        stack: set[int] = set()

        def visit(n: int) -> bool:
            if n in stack:
                return True
            if n in seen:
                return False
            stack.add(n)
            for d in deps.get(n, ()):
                if visit(d):
                    return True
            stack.discard(n)
            seen.add(n)
            return False

        return any(visit(i) for i in deps)

    def ready_steps(self, done: set[int]) -> list[PlanStep]:
        """Các step chưa chạy mà mọi depends_on đã có trong `done` -> dispatch song song."""
        return [
            s for s in self.steps
            if s.id not in done and all(d in done for d in s.depends_on)
        ]


def plan_json_schema() -> dict[str, Any]:
    """JSON Schema để bind structured output cho orchestrator."""
    return Plan.model_json_schema()
