"""Planner sentinel 'react' — đánh dấu dùng graph LangGraph CŨ (shortcut→think→act→...).

graph_builder thấy mode=react thì build graph cũ, KHÔNG gọi planner này. Giữ để registry
có đủ tên + rollback rõ ràng. plan() không dùng tới; raise nếu lỡ gọi.
"""
from __future__ import annotations

from app.agents.plan_schema import Plan
from app.agents.planners.base import PlanContext, Planner
from app.agents.registry import register_planner


@register_planner("react")
class ReactPlanner(Planner):
    name = "react"

    async def plan(self, ctx: PlanContext) -> Plan:  # pragma: no cover
        raise RuntimeError("react planner không sinh Plan — dùng graph LangGraph cũ")
