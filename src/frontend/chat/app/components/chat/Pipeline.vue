<script setup lang="ts">
import { Search, Database, Loader2, CheckCircle2, Sparkles, Cpu } from '@lucide/vue'
import type { TraceEntry, NodeModel } from '~/types'

interface Props {
  traceLog: TraceEntry[]
  thinkingStatus?: string
  isThinking?: boolean
  models?: NodeModel[]
  thoughts?: { node: string; text: string }[]
}

const props = defineProps<Props>()

const NODE_LABEL: Record<string, string> = {
  triage: 'Phân loại',
  think: 'Lập kế hoạch',
  answer: 'Soạn trả lời',
}

const TOOL_LABEL: Record<string, string> = {
  rag_search: 'Tìm kiếm tài liệu',
  hr_query: 'Truy vấn dữ liệu HR',
}

const TOOL_ICON: Record<string, any> = {
  rag_search: Search,
  hr_query: Database,
}

function getQueryLabel(entry: TraceEntry): string {
  const args = entry.args
  if (entry.tool === 'rag_search') {
    const q = (args.query as string) || ''
    return q ? `"${q}"` : ''
  }
  if (entry.tool === 'hr_query') {
    const intent = (args.intent as string) || ''
    const labelMap: Record<string, string> = {
      leave_balance: 'số ngày phép còn lại',
      leave_requests: 'lịch sử đơn nghỉ phép',
      payroll: 'thông tin lương',
    }
    return labelMap[intent] || intent
  }
  return ''
}

function getResultLabel(entry: TraceEntry): string {
  if (entry.tool === 'rag_search') {
    const count = entry.resultCount ?? 0
    if (count === 0) return 'Không tìm thấy kết quả'
    const docs = entry.resultDocs ?? []
    const docStr = docs.length > 0 ? ` — ${docs.slice(0, 2).join(', ')}${docs.length > 2 ? '...' : ''}` : ''
    return `${count} tài liệu${docStr}`
  }
  if (entry.tool === 'hr_query' && entry.resultRaw) {
    return entry.resultRaw.slice(0, 60) + (entry.resultRaw.length > 60 ? '…' : '')
  }
  return ''
}
</script>

<template>
  <div class="rounded-xl bg-transparent px-4 py-3">
    <div class="mb-2.5 flex items-center gap-2 text-[12px] font-medium text-slate-700 dark:text-foreground/80">
      <Sparkles class="h-3.5 w-3.5 text-blue-500" />
      Agent đang xử lý
    </div>

    <!-- Model badges live: node nào vừa chạy model nào (minh bạch vận hành) -->
    <div v-if="models?.length" class="mb-2 flex flex-wrap items-center gap-1">
      <span
        v-for="(m, i) in models"
        :key="i"
        class="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[10.5px] font-medium text-slate-600 dark:bg-white/10 dark:text-slate-300"
      >
        <Cpu class="h-3 w-3 text-blue-500" />
        {{ NODE_LABEL[m.node] ?? m.node }}: {{ m.model }}
      </span>
    </div>

    <!-- Suy nghĩ / quyết định của model (live) -->
    <div v-if="thoughts?.length" class="mb-2 space-y-1">
      <div
        v-for="(t, i) in thoughts"
        :key="i"
        class="rounded-lg border border-blue-100 bg-blue-50/50 px-3 py-1.5 text-[11.5px] leading-relaxed text-slate-600 dark:border-blue-500/15 dark:bg-blue-500/5 dark:text-muted-foreground"
      >
        <span class="font-semibold text-blue-600 dark:text-blue-300">{{ NODE_LABEL[t.node] ?? t.node }}:</span>
        {{ t.text }}
      </div>
    </div>

    <!-- Thinking indicator (before any tool calls) -->
    <div
      v-if="isThinking && traceLog.length === 0"
      class="flex items-center gap-2.5 rounded-md px-2 py-1.5"
    >
      <Loader2 class="h-3.5 w-3.5 shrink-0 animate-spin text-blue-500" />
      <span class="text-[12.5px] text-slate-600 dark:text-muted-foreground animate-pulse">
        {{ thinkingStatus || 'Đang suy nghĩ…' }}
      </span>
    </div>

    <!-- Trace entries -->
    <div class="space-y-1">
      <div
        v-for="(entry, i) in traceLog"
        :key="i"
        class="rounded-lg border border-slate-100 dark:border-white/5 bg-slate-50/60 dark:bg-white/[0.03] px-3 py-2"
      >
        <!-- Tool header row -->
        <div class="flex items-center gap-2">
          <component
            :is="TOOL_ICON[entry.tool] ?? Search"
            class="h-3.5 w-3.5 shrink-0 text-blue-500"
          />
          <span class="text-[12px] font-semibold text-slate-700 dark:text-foreground/80">
            {{ TOOL_LABEL[entry.tool] ?? entry.tool }}
          </span>
          <span v-if="getQueryLabel(entry)" class="flex-1 truncate text-[11.5px] text-slate-500 dark:text-muted-foreground">
            {{ getQueryLabel(entry) }}
          </span>
          <Loader2
            v-if="entry.pending"
            class="h-3 w-3 shrink-0 animate-spin text-blue-400"
          />
          <CheckCircle2
            v-else
            class="h-3 w-3 shrink-0 text-emerald-500"
          />
        </div>

        <!-- Result row -->
        <div
          v-if="!entry.pending"
          class="mt-1 pl-5 text-[11px] text-slate-500 dark:text-muted-foreground/80"
        >
          {{ getResultLabel(entry) }}
        </div>
      </div>

      <!-- Pending thinking status after tool calls -->
      <div
        v-if="isThinking && traceLog.length > 0"
        class="flex items-center gap-2 px-1 py-1"
      >
        <Loader2 class="h-3 w-3 shrink-0 animate-spin text-blue-400" />
        <span class="text-[11.5px] text-slate-500 dark:text-muted-foreground animate-pulse">
          {{ thinkingStatus || 'Đang tổng hợp kết quả…' }}
        </span>
      </div>
    </div>
  </div>
</template>
