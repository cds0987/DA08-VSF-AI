<script setup lang="ts">
// Hiển thị BỀN VỮNG các bước agent đã thực hiện (tool calls + kết quả) dưới mỗi câu trả lời.
// Khác Pipeline.vue (chỉ live lúc đang stream rồi biến mất), component này gắn vào message
// -> user có thể mở lại xem agent đã tra tài liệu nào, thấy bao nhiêu kết quả.
import { Search, Database, CheckCircle2, ChevronRight, Sparkles, Cpu } from '@lucide/vue'
import type { TraceEntry, NodeModel } from '~/types'

const props = defineProps<{ trace: TraceEntry[]; models?: NodeModel[] }>()

const open = ref(false)

const NODE_LABEL: Record<string, string> = {
  triage: 'Phân loại',
  think: 'Lập kế hoạch',
  answer: 'Soạn trả lời',
}

const TOOL_LABEL: Record<string, string> = {
  rag_search: 'Tìm kiếm tài liệu',
  hr_query: 'Truy vấn dữ liệu HR',
  leave_approvals: 'Lấy danh sách đơn chờ duyệt',
  resolve_date: 'Xác định ngày',
  leave_types: 'Lấy danh mục loại nghỉ',
}
const TOOL_ICON: Record<string, any> = {
  rag_search: Search,
  hr_query: Database,
}

function queryLabel(e: TraceEntry): string {
  if (e.tool === 'rag_search') {
    const q = (e.args.query as string) || ''
    return q ? `"${q}"` : ''
  }
  return (e.args.intent as string) || ''
}

function resultLabel(e: TraceEntry): string {
  if (e.tool === 'rag_search') {
    const count = e.resultCount ?? 0
    if (count === 0) return 'Không tìm thấy kết quả'
    const docs = e.resultDocs ?? []
    const docStr = docs.length ? ` — ${docs.slice(0, 3).join(', ')}${docs.length > 3 ? '…' : ''}` : ''
    return `${count} tài liệu${docStr}`
  }
  if (e.resultRaw) return e.resultRaw.slice(0, 80) + (e.resultRaw.length > 80 ? '…' : '')
  return 'Hoàn tất'
}
</script>

<template>
  <div v-if="trace.length || models?.length" class="mb-2.5">
    <!-- Header toggle -->
    <button
      v-if="trace.length"
      class="group flex items-center gap-1.5 rounded-md px-2 py-1 text-[12px] font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-muted-foreground dark:hover:bg-white/5 dark:hover:text-foreground"
      @click="open = !open"
    >
      <Sparkles class="h-3.5 w-3.5 text-blue-500" />
      <span>Agent đã thực hiện {{ trace.length }} bước</span>
      <ChevronRight
        class="h-3.5 w-3.5 transition-transform"
        :class="open && 'rotate-90'"
      />
    </button>

    <!-- Model badges (minh bạch vận hành: node nào chạy model nào) — luôn hiện -->
    <div v-if="models?.length" class="mt-1 flex flex-wrap items-center gap-1 px-2">
      <span
        v-for="(m, i) in models"
        :key="i"
        class="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[10.5px] font-medium text-slate-600 dark:bg-white/10 dark:text-slate-300"
        :title="`${NODE_LABEL[m.node] ?? m.node} · ${m.model}`"
      >
        <Cpu class="h-3 w-3 text-blue-500" />
        {{ NODE_LABEL[m.node] ?? m.node }}: {{ m.model }}
      </span>
    </div>

    <!-- Steps -->
    <div v-if="open" class="mt-1.5 space-y-1 pl-1">
      <div
        v-for="(e, i) in trace"
        :key="i"
        class="rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2 dark:border-white/5 dark:bg-white/[0.03]"
      >
        <div class="flex items-center gap-2">
          <component :is="TOOL_ICON[e.tool] ?? Search" class="h-3.5 w-3.5 shrink-0 text-blue-500" />
          <span class="text-[12px] font-semibold text-slate-700 dark:text-foreground/80">
            {{ TOOL_LABEL[e.tool] ?? e.tool }}
          </span>
          <span v-if="queryLabel(e)" class="flex-1 truncate text-[11.5px] text-slate-500 dark:text-muted-foreground">
            {{ queryLabel(e) }}
          </span>
          <CheckCircle2 class="h-3 w-3 shrink-0 text-emerald-500" />
        </div>
        <div class="mt-1 pl-5 text-[11px] text-slate-500 dark:text-muted-foreground/80">
          {{ resultLabel(e) }}
        </div>
      </div>
    </div>
  </div>
</template>
