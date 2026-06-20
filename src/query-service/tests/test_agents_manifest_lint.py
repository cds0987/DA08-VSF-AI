"""GATE deploy: agents.yaml PHẢI nhất quán + DEFAULT-OFF (prod an toàn khi chưa ổn định).

Lệch là CI đỏ -> chặn build+deploy (Phase GATE). Bắt các lỗi cấu hình TRƯỚC prod:
- role.name trong manifest chưa @register -> orchestrator gọi sẽ KeyError.
- capability lạ -> ai-router không route được.
- tool lạ -> mcp-service không có tool.
- mode committed != react -> RỦI RO bật orchestrator chưa ổn định lên prod.
"""
from __future__ import annotations

from app.agents import planners, roles  # noqa: F401 — register
from app.agents.manifest import load_manifest
from app.agents.registry import AGENT_REGISTRY, PLANNER_REGISTRY

# Capability hợp lệ = phải có trong src/ai-router/routing.yaml (cross-service contract).
_ALLOWED_CAPABILITIES = {"worker", "answer", "think", "guardrail", "rerank", "triage"}
# Tool hợp lệ = mcp-service expose (rag_search, hr_query, resolve_date). Cập nhật khi thêm tool MCP.
_ALLOWED_TOOLS = {"rag_search", "hr_query", "resolve_date"}


def test_committed_mode_is_react_default_off():
    """DEFAULT-OFF: manifest commit PHẢI để mode=react -> prod chạy flow cũ ổn định.
    Bật orchestrator_workers chỉ qua override env/manifest sau khi A/B xanh — KHÔNG commit."""
    m = load_manifest()
    assert m.mode == "react", (
        f"agents.yaml commit mode={m.mode!r} — chỉ được commit 'react' (default-off). "
        "Bật orchestrator_workers qua env override khi A/B, đừng commit."
    )


def test_all_roles_registered():
    m = load_manifest()
    for r in m.roles:
        assert AGENT_REGISTRY.has(r.name), f"role '{r.name}' trong agents.yaml chưa @register_agent"


def test_all_capabilities_valid():
    m = load_manifest()
    for r in m.roles:
        assert r.capability in _ALLOWED_CAPABILITIES, (
            f"role '{r.name}' capability='{r.capability}' không có trong routing.yaml "
            f"({sorted(_ALLOWED_CAPABILITIES)})"
        )


def test_role_tools_known():
    m = load_manifest()
    for r in m.roles:
        for t in r.tools:
            assert t in _ALLOWED_TOOLS, f"role '{r.name}' tool='{t}' không phải tool MCP hợp lệ"


def test_planner_registered():
    m = load_manifest()
    assert PLANNER_REGISTRY.has(m.planner), f"planner '{m.planner}' chưa đăng ký"


def test_synthesize_role_present():
    """Orchestrator-Workers cần đúng 1 role tổng hợp cuối."""
    m = load_manifest()
    assert "synthesize_recommend" in {r.name for r in m.roles}
