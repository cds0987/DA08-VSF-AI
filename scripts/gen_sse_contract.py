#!/usr/bin/env python3
"""Sinh type TS cho FE TỪ hợp đồng SSE Python (app/agents/sse_contract.py) -> 2 đầu (Python
emit + TS consume) DÙNG CHUNG 1 nguồn sự thật.

Chạy: python scripts/gen_sse_contract.py
CI gate: chạy lại + `git diff --exit-code` file .gen.ts -> lệch (quên regen sau khi đổi
contract) = ĐỎ -> ép FE đồng bộ với backend.

Thêm node/phase/tool vào sse_contract.py -> chạy script này -> FE tự có map mới -> render
generic theo group (KHÔNG cần sửa tay FE).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QS_APP = ROOT / "src" / "query-service"
OUT = ROOT / "src" / "frontend" / "chat" / "app" / "types" / "sse-contract.gen.ts"

sys.path.insert(0, str(QS_APP))


def _ts(manifest: dict) -> str:
    j = lambda v: json.dumps(v, ensure_ascii=False, indent=2)  # noqa: E731
    return f"""\
// ⚠️ FILE SINH TỰ ĐỘNG — KHÔNG SỬA TAY.
// Nguồn: src/query-service/app/agents/sse_contract.py
// Sinh lại: python scripts/gen_sse_contract.py  (CI có gate diff -> lệch = đỏ)
//
// 1 NGUỒN SỰ THẬT cho hợp đồng SSE FE↔query: node tự mô tả (label/group/icon) ->
// FE render GENERIC theo group; thêm node ở backend = tự hiện đúng nhóm, không sửa FE.

export const SSE_CONTRACT_VERSION = {manifest['version']} as const

// Nhóm hiển thị có THỨ TỰ (FE vẽ khúc agent theo đúng thứ tự logic này).
export const SSE_GROUPS = {j(manifest['groups'])} as const
export type SseGroup = (typeof SSE_GROUPS)[number]

export interface SseNodeDescriptor {{
  label: string
  group: SseGroup
  icon: string
}}

// node -> cách hiển thị. FE gom thought theo .group, dán nhãn .label, chọn icon .icon.
export const SSE_NODES: Record<string, SseNodeDescriptor> = {j(manifest['nodes'])}

// Tập phase hợp lệ (FE có thể assert / log khi gặp phase lạ).
export const SSE_PHASES = {j(manifest['phases'])} as const
export type SsePhase = (typeof SSE_PHASES)[number]

// tool -> nhãn tiếng Việt (khúc "agent đã làm").
export const SSE_TOOLS: Record<string, string> = {j(manifest['tools'])}

// Field BẮT BUỘC của done-event (thiếu -> tin nhắn treo). Khớp isDoneEvent ở chat store.
export const SSE_DONE_REQUIRED = {j(manifest['done_required'])} as const

// Tra group của 1 node (fallback 'orchestrator' cho node lạ chưa kịp khai -> KHÔNG mất khúc).
export function nodeGroup(node: string | undefined): SseGroup {{
  return (node && SSE_NODES[node]?.group) || 'orchestrator'
}}
"""


def main() -> int:
    from app.agents.sse_contract import contract_manifest  # noqa: E402

    manifest = contract_manifest()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(_ts(manifest), encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
