"""HỢP ĐỒNG SSE — 1 NGUỒN SỰ THẬT cho mọi event query-service đẩy ra FE.

Vấn đề gốc: FE render theo `phase`/`node`/`tool` trong event SSE, nhưng hợp đồng này
trước đây nằm RẢI RÁC (literal "phase":"..." khắp graph_builder/roles/orchestration) +
hardcode ở FE (MessageSteps gom node theo list cứng). Thêm 1 node MỚI vào graph mà quên
khai báo cách hiển thị -> event ra UI bị FE BỎ QUA ÂM THẦM (không lỗi, chỉ mất khúc).

Module này gom TOÀN BỘ từ vựng SSE về 1 chỗ:
- PHASES: tập `phase` hợp lệ.
- NODES: mỗi node TỰ MÔ TẢ cách hiển thị (label + group UI + icon) -> thêm node = PHẢI
  khai NodeDescriptor (else gate test đỏ) -> KHÔNG bao giờ "câm" trên UI.
- GROUPS: nhóm hiển thị có thứ tự (orchestrator -> worker -> verify -> answer).
- TOOLS: nhãn tool (khớp FE).
- DONE_REQUIRED: field bắt buộc của done-event (thiếu -> FE treo).

`contract_manifest()` xuất JSON -> sinh type TS cho FE (scripts/gen_sse_contract.py) ->
2 đầu (Python emit + TS consume) DÙNG CHUNG 1 hợp đồng, drift = CI đỏ.

`validate_event()` fail-safe: prod chỉ CẢNH BÁO (không bao giờ làm vỡ câu trả lời); test
gọi strict=True để bắt lỗi sớm.
"""
from __future__ import annotations

from dataclasses import dataclass

# Version hợp đồng — tăng khi đổi shape (FE đọc để phát hiện lệch lúc rolling-deploy).
CONTRACT_VERSION = 1


# ───────────────────────────── GROUPS (nhóm hiển thị UI, có thứ tự) ─────────────────────────────
# FE vẽ khúc "agent đã làm" theo các nhóm này, ĐÚNG THỨ TỰ logic. Thêm group mới -> khai ở đây
# + FE renderer đọc từ manifest (không hardcode).
GROUPS: tuple[str, ...] = ("orchestrator", "worker", "verify", "answer")


@dataclass(frozen=True)
class NodeDescriptor:
    """Mô tả 1 node graph/agent TỰ HIỂN THỊ. label/group/icon -> FE render generic (không cần
    sửa FE khi thêm node). group PHẢI ∈ GROUPS. icon = tên icon lucide (FE map sang component)."""
    name: str
    label: str
    group: str
    icon: str


def _nd(name: str, label: str, group: str, icon: str) -> NodeDescriptor:
    assert group in GROUPS, f"node {name!r}: group {group!r} không ∈ GROUPS {GROUPS}"
    return NodeDescriptor(name=name, label=label, group=group, icon=icon)


# ───────────────────────────── NODES (mỗi node TỰ MÔ TẢ) ─────────────────────────────
# Đây là chỗ DUY NHẤT khai node. Thêm node vào graph/react -> THÊM 1 dòng ở đây (else gate
# test "no undeclared node" đỏ). FE đọc map này (sinh ra TS) -> tự hiện đúng nhóm + nhãn + icon.
NODES: dict[str, NodeDescriptor] = {
    # Orchestrator (lập kế hoạch + suy luận điều phối)
    "orchestrate": _nd("orchestrate", "Điều phối", "orchestrator", "GitBranch"),
    "plan":        _nd("plan", "Lập kế hoạch", "orchestrator", "GitBranch"),
    "think":       _nd("think", "Suy luận", "orchestrator", "Sparkles"),
    # Worker (react path: vòng hành động đơn)
    "act":         _nd("act", "Hành động", "worker", "Search"),
    # Verify (think 2 — kiểm tra đủ thông tin + tổng hợp)
    "verify":      _nd("verify", "Kiểm tra & tổng hợp", "verify", "ShieldCheck"),
    # Answer (soạn câu trả lời cuối)
    "answer":      _nd("answer", "Soạn câu trả lời", "answer", "Sparkles"),
}


# ───────────────────────────── PHASES (tập `phase` hợp lệ) ─────────────────────────────
PHASES: frozenset[str] = frozenset({
    "thinking",    # node bắt đầu nghĩ -> kèm status (FE: thinkingStatus)
    "acting",      # gọi tool -> kèm tool (+tool_args)
    "observing",   # tool trả kết quả -> kèm tool (+tool_result_summary)
    "generating",  # token câu trả lời chạy dần -> kèm token
    "plan",        # orchestrator phát kế hoạch -> kèm route + steps[]
    "step",        # 1 node đổi trạng thái -> kèm step_id + status
    "thought",     # model "đang nghĩ" (reasoning/prose) -> kèm node + text
    "model_used",  # model THẬT 1 node đã chạy -> kèm node + model (minh bạch vận hành)
})


# ───────────────────────────── TOOLS (nhãn — khớp FE TOOL_LABEL) ─────────────────────────────
TOOLS: dict[str, str] = {
    "rag_search": "Tìm kiếm tài liệu",
    "hr_query": "Truy vấn dữ liệu HR",
    "leave_approvals": "Lấy danh sách đơn chờ duyệt",
    "resolve_date": "Xác định ngày",
    "leave_types": "Lấy danh mục loại nghỉ",
}


# ───────────────────────────── DONE-EVENT (field bắt buộc) ─────────────────────────────
# FE.isDoneEvent yêu cầu ĐỦ các field này (đúng type) mới chốt tin nhắn; thiếu 1 -> event bị
# BỎ QUA -> tin nhắn TREO. Giữ list này khớp FE -> đổi = phải đổi cả 2 đầu (gate bắt).
DONE_REQUIRED: frozenset[str] = frozenset({"done", "session_id", "sources"})


# ───────────────────────────── VALIDATE (fail-safe) ─────────────────────────────
def validate_event(ev: dict, *, strict: bool = False) -> list[str]:
    """Soi 1 event SSE so với hợp đồng. Trả DANH SÁCH vấn đề (rỗng = hợp lệ).

    - done-event: phải đủ DONE_REQUIRED.
    - event thường: `phase` (nếu có) ∈ PHASES; `node` (nếu có) ∈ NODES.
    - Event chỉ mang token (không phase) vẫn hợp lệ (token delta).

    strict=True -> raise ValueError nếu có vấn đề (DÙNG TRONG TEST). Prod gọi strict=False
    rồi log cảnh báo -> KHÔNG bao giờ làm vỡ câu trả lời (fail-safe)."""
    problems: list[str] = []
    if not isinstance(ev, dict):
        problems.append(f"event không phải dict: {type(ev).__name__}")
        if strict:
            raise ValueError("; ".join(problems))
        return problems

    if ev.get("done") is True:
        missing = [f for f in DONE_REQUIRED if f not in ev]
        if missing:
            problems.append(f"done-event THIẾU field bắt buộc: {sorted(missing)}")
    else:
        phase = ev.get("phase")
        if phase is not None and phase not in PHASES:
            problems.append(f"phase {phase!r} KHÔNG ∈ PHASES (chưa khai trong sse_contract)")
        node = ev.get("node")
        if node is not None and node not in NODES:
            problems.append(
                f"node {node!r} KHÔNG ∈ NODES — thêm NodeDescriptor vào sse_contract.NODES "
                "(else event sẽ CÂM trên UI)"
            )

    if problems and strict:
        raise ValueError("; ".join(problems))
    return problems


# ───────────────────────────── MANIFEST (xuất cho FE codegen) ─────────────────────────────
def contract_manifest() -> dict:
    """Hợp đồng dạng JSON -> sinh TS cho FE (1 nguồn sự thật cho cả 2 đầu).

    FE đọc: nodes (node->{label,group,icon}) để render generic, groups (thứ tự), phases,
    tools, done_required, version. Thêm node/phase/tool ở trên -> manifest đổi -> codegen
    sinh lại TS -> CI diff gate ép FE đồng bộ (else đỏ)."""
    return {
        "version": CONTRACT_VERSION,
        "groups": list(GROUPS),
        "nodes": {
            n: {"label": d.label, "group": d.group, "icon": d.icon}
            for n, d in NODES.items()
        },
        "phases": sorted(PHASES),
        "tools": dict(TOOLS),
        "done_required": sorted(DONE_REQUIRED),
    }
