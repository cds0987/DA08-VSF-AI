// ⚠️ FILE SINH TỰ ĐỘNG — KHÔNG SỬA TAY.
// Nguồn: src/query-service/app/agents/sse_contract.py
// Sinh lại: python scripts/gen_sse_contract.py  (CI có gate diff -> lệch = đỏ)
//
// 1 NGUỒN SỰ THẬT cho hợp đồng SSE FE↔query: node tự mô tả (label/group/icon) ->
// FE render GENERIC theo group; thêm node ở backend = tự hiện đúng nhóm, không sửa FE.

export const SSE_CONTRACT_VERSION = 1 as const

// Nhóm hiển thị có THỨ TỰ (FE vẽ khúc agent theo đúng thứ tự logic này).
export const SSE_GROUPS = [
  "orchestrator",
  "worker",
  "verify",
  "answer"
] as const
export type SseGroup = (typeof SSE_GROUPS)[number]

export interface SseNodeDescriptor {
  label: string
  group: SseGroup
  icon: string
}

// node -> cách hiển thị. FE gom thought theo .group, dán nhãn .label, chọn icon .icon.
export const SSE_NODES: Record<string, SseNodeDescriptor> = {
  "orchestrate": {
    "label": "Điều phối",
    "group": "orchestrator",
    "icon": "GitBranch"
  },
  "plan": {
    "label": "Lập kế hoạch",
    "group": "orchestrator",
    "icon": "GitBranch"
  },
  "think": {
    "label": "Suy luận",
    "group": "orchestrator",
    "icon": "Sparkles"
  },
  "act": {
    "label": "Hành động",
    "group": "worker",
    "icon": "Search"
  },
  "verify": {
    "label": "Kiểm tra & tổng hợp",
    "group": "verify",
    "icon": "ShieldCheck"
  },
  "answer": {
    "label": "Soạn câu trả lời",
    "group": "answer",
    "icon": "Sparkles"
  }
}

// Tập phase hợp lệ (FE có thể assert / log khi gặp phase lạ).
export const SSE_PHASES = [
  "acting",
  "generating",
  "model_used",
  "observing",
  "plan",
  "step",
  "thinking",
  "thought"
] as const
export type SsePhase = (typeof SSE_PHASES)[number]

// tool -> nhãn tiếng Việt (khúc "agent đã làm").
export const SSE_TOOLS: Record<string, string> = {
  "rag_search": "Tìm kiếm tài liệu",
  "hr_query": "Truy vấn dữ liệu HR",
  "leave_approvals": "Lấy danh sách đơn chờ duyệt",
  "resolve_date": "Xác định ngày",
  "leave_types": "Lấy danh mục loại nghỉ"
}

// Field BẮT BUỘC của done-event (thiếu -> tin nhắn treo). Khớp isDoneEvent ở chat store.
export const SSE_DONE_REQUIRED = [
  "done",
  "session_id",
  "sources"
] as const

// Tra group của 1 node (fallback 'orchestrator' cho node lạ chưa kịp khai -> KHÔNG mất khúc).
export function nodeGroup(node: string | undefined): SseGroup {
  return (node && SSE_NODES[node]?.group) || 'orchestrator'
}
