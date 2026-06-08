from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable

from app.core.config import McpSettings
from app.tools.registry import Registry


@runtime_checkable
class McpTool(Protocol):
    name: str

    def register(self, mcp: Any) -> None:
        ...

    async def verify(self) -> None:
        ...

    async def aclose(self) -> None:
        ...


ToolFactory = Callable[[McpSettings, Mapping[str, Any]], McpTool]
_TOOL_REGISTRY: Registry[ToolFactory] = Registry(
    "tool",
    entry_point_group="mcp_service.tool",
)


def register_tool(name: str, factory: ToolFactory, *, override: bool = False) -> None:
    _TOOL_REGISTRY.register(name, factory, override=override)


def resolve_tool(
    name: str,
    *,
    settings: McpSettings,
    params: Mapping[str, Any],
) -> McpTool:
    return _TOOL_REGISTRY.get(name)(settings, dict(params or {}))


def available_tools() -> list[str]:
    return _TOOL_REGISTRY.available()


def is_entry_point_tool(name: str) -> bool:
    return _TOOL_REGISTRY.is_entry_point(name)
