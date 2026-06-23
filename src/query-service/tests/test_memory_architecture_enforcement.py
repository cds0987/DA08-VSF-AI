"""GATE memory (đỏ = chặn deploy) — ép kỷ luật kiến trúc, dev mới đụng không phá được.

1 stateless-worker · 2 boundary · 3 contract-complete · 4 shape-drift · 5 token-bound
· 6 fail-safe · 7 hot-config · 8 mock-default · 9 ACL-isolation.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from app.agents.memory.client import InProcessMemoryClient
from app.agents.memory.contracts import (
    MemoryClient, MemoryContext, TaskState, WorkingSetItem,
)
from app.agents.memory.redis_store import NoOpStmStore

_APP = Path(__file__).resolve().parents[1] / "app"
_ROLES = _APP / "agents" / "roles"


# ───────── GATE 1: worker STATELESS — KHÔNG chạm memory store/client ─────────
def test_workers_do_not_import_memory_client():
    bad = []
    for p in _ROLES.glob("*.py"):
        src = p.read_text(encoding="utf-8")
        if "memory.client" in src or "memory.redis_store" in src or "MemoryClient" in src:
            bad.append(p.name)
    assert not bad, (
        f"Worker/role PHẢI stateless — KHÔNG được chạm memory store/client: {bad}. "
        "Working-set/task-state là việc của tầng ĐIỀU PHỐI (planner/orchestration)."
    )


# ───────── GATE 2: BOUNDARY — load_context chỉ ở orchestration ─────────
def test_load_context_only_at_orchestration_boundary():
    offenders = []
    for p in _APP.rglob("*.py"):
        if "agents/memory" in p.as_posix():
            continue  # định nghĩa, bỏ qua
        if "load_context(" in p.read_text(encoding="utf-8"):
            # chỉ cho phép trong use_cases/query (orchestration)
            if "use_cases/query" not in p.as_posix():
                offenders.append(p.as_posix())
    assert not offenders, f"load_context chỉ được gọi ở orchestration, thấy ở: {offenders}"


# ───────── GATE 3: CONTRACT COMPLETE — adapter impl đủ Protocol ─────────
def test_adapters_implement_memory_client_protocol():
    for cls in (InProcessMemoryClient,):
        for m in ("load_context", "record_turn", "get_task_state", "set_task_state", "add_evidence"):
            assert callable(getattr(cls, m, None)), f"{cls.__name__} thiếu method contract: {m}"


# ───────── GATE 4: SHAPE DRIFT — MemoryContext không lệch contract ─────────
_EXPECTED_MEMORY_FIELDS = {"dialogue", "summary", "task_state", "working_set", "preferences"}

def test_memory_context_shape_no_drift():
    actual = {f.name for f in dataclasses.fields(MemoryContext)}
    assert actual == _EXPECTED_MEMORY_FIELDS, (
        f"MemoryContext lệch contract. Đổi field phải update test + MOSA consumer. "
        f"actual={sorted(actual)} expected={sorted(_EXPECTED_MEMORY_FIELDS)}"
    )


def _client(loader, n=7):
    return InProcessMemoryClient(stm_store=NoOpStmStore(), dialogue_loader=loader, recent_n=n)


# ───────── GATE 5: TOKEN-BOUND — dialogue ≤ recent_n dù hội thoại 100 lượt ─────────
async def test_dialogue_token_bounded():
    async def loader(uid, cid):
        return [("user", f"m{i}") for i in range(100)]
    ctx = await _client(loader, n=7).load_context("u1", "c1", "q")
    assert len(ctx.dialogue) == 7, "dialogue KHÔNG bị giới hạn -> phình token/quota"


# ───────── GATE 6: FAIL-SAFE — loader lỗi -> context rỗng, KHÔNG raise ─────────
async def test_load_context_fail_safe():
    async def bad_loader(uid, cid):
        raise RuntimeError("db down")
    ctx = await _client(bad_loader).load_context("u1", "c1", "q")
    assert ctx == MemoryContext.empty(), "memory lỗi PHẢI degrade rỗng, KHÔNG làm vỡ query"


# ───────── GATE 7: HOT-CONFIG — recent_n đọc từ settings, không hardcode ─────────
def test_recent_n_from_settings():
    from app.agents.memory.builder import build_memory_client

    class S:
        memory_enabled = True; redis_url = ""; memory_recent_n = 3; memory_summarize_after = 9
    async def loader(uid, cid): return []
    c = build_memory_client(S(), dialogue_loader=loader, make_model=None)
    assert c._recent_n == 3, "recent_n phải đọc từ settings (hot-config), không hardcode"


# ───────── GATE 8: MOCK/DEFAULT — memory_enabled=false -> None (rollback an toàn) ─────────
def test_memory_disabled_returns_none():
    from app.agents.memory.builder import build_memory_client

    class S:
        memory_enabled = False; redis_url = "redis://x"
    async def loader(uid, cid): return []
    assert build_memory_client(S(), dialogue_loader=loader, make_model=None) is None


def test_no_redis_falls_back_to_noop_store():
    from app.agents.memory.builder import build_memory_client
    from app.agents.memory.redis_store import NoOpStmStore as NoOp

    class S:
        memory_enabled = True; redis_url = ""
    async def loader(uid, cid): return []
    c = build_memory_client(S(), dialogue_loader=loader, make_model=None)
    assert isinstance(c._stm, NoOp)


# ───────── GATE 9: ACL ISOLATION — user A KHÔNG đọc được memory user B ─────────
async def test_acl_task_state_isolated_per_user():
    store = NoOpStmStore()
    await store.set_task("userA", "conv1", TaskState(flow="create_leave", data={"x": 1}))
    # cùng conv_id nhưng KHÁC user -> KHÔNG được thấy
    assert await store.get_task("userB", "conv1") is None, "RÒ task-state CHÉO user (ACL vỡ)!"
    assert (await store.get_task("userA", "conv1")).flow == "create_leave"


async def test_acl_working_set_isolated_per_user():
    store = NoOpStmStore()
    await store.add_evidence("userA", "conv1", WorkingSetItem(kind="rag", label="phép năm"))
    assert len((await store.get_ws("userB", "conv1")).items) == 0, "RÒ working-set CHÉO user!"
    assert len((await store.get_ws("userA", "conv1")).items) == 1


# ───────── GATE 10: MEM-3 — THIẾU conv_id -> STATELESS (không bleed bucket chung) ─────────
@pytest.mark.parametrize("blank", [None, "", "   "])
async def test_missing_conv_id_is_stateless_no_bleed(blank):
    """Không có conversation_id -> KHÔNG ghi/đọc STM. Trước đây conv rỗng dồn 1 bucket
    mem:task:{uid}: -> mọi query không-conv của user dùng CHUNG trí nhớ (bleed)."""
    store = NoOpStmStore()
    await store.set_task("userA", blank, TaskState(flow="create_leave", data={"x": 1}))
    await store.add_evidence("userA", blank, WorkingSetItem(kind="rag", label="phép năm"))
    # ghi không có tác dụng -> đọc lại rỗng (mỗi query độc lập, không nhiễm)
    assert await store.get_task("userA", blank) is None, "MEM-3: task-state bleed khi thiếu conv_id!"
    assert len((await store.get_ws("userA", blank)).items) == 0, "MEM-3: working-set bleed!"
