<script setup lang="ts">
// Bao gồm: bước tool, model từng node, và suy nghĩ/quyết định của model (minh bạch tư duy).
// Hiển thị BỀN VỮNG các bước agent đã thực hiện (tool calls + kết quả) dưới mỗi câu trả lời.
// Khác Pipeline.vue (chỉ live lúc đang stream rồi biến mất), component này gắn vào message
// -> user có thể mở lại xem agent đã tra tài liệu nào, thấy bao nhiêu kết quả.
import { Search, Database, CheckCircle2, ChevronRight, Sparkles } from '@lucide/vue'
import type { TraceEntry, NodeModel, Thought } from '~/types'

const props = defineProps<{ trace: TraceEntry[]; models?: NodeModel[]; thoughts?: Thought[] }>()

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
  <div v-if="trace.length || models?.length || thoughts?.length" class="mb-2.5">
    <!-- Header toggle -->
    <button
      v-if="trace.length || thoughts?.length"
      class="group flex items-center gap-1.5 rounded-md px-2 py-1 text-[12px] font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-muted-foreground dark:hover:bg-white/5 dark:hover:text-foreground"
      @click="open = !open"
    >
      <Sparkles class="h-3.5 w-3.5 text-blue-500" />
      <span>{{ trace.length ? `Agent đã thực hiện ${trace.length} bước` : 'Xem suy nghĩ của agent' }}</span>
      <ChevronRight
        class="h-3.5 w-3.5 transition-transform"
        :class="open && 'rotate-90'"
      />
    </button>

    <!-- Suy nghĩ / quyết định của model -->
    <div v-if="open && thoughts?.length" class="mt-1.5 space-y-1 pl-1">
      <div
        v-for="(t, i) in thoughts"
        :key="`th-${i}`"
        class="rounded-lg border border-blue-100 bg-blue-50/50 px-3 py-1.5 text-[11.5px] leading-relaxed text-slate-600 dark:border-blue-500/15 dark:bg-blue-500/5 dark:text-muted-foreground"
      >
        <span class="font-semibold text-blue-600 dark:text-blue-300">{{ NODE_LABEL[t.node] ?? t.node }}:</span>
        {{ t.text }}
      </div>
    </div>

    <!-- Steps -->
    <div v-if="open && trace.length" class="mt-1.5 space-y-1 pl-1">
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
