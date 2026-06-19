<script setup lang="ts">
// Hiển thị KẾ HOẠCH orchestrator-workers: các node theo LEVEL (depends_on). Node cùng level
// chạy SONG SONG -> render cùng 1 hàng (nhiều cột) để user thấy subagents chạy song song.
import { Loader2, CheckCircle2, XCircle, Circle, FileSearch, Database, Sparkles, Lightbulb, ShieldCheck } from '@lucide/vue'
import { computed } from 'vue'
import type { AgentPlan } from '~/types'

const props = defineProps<{ plan: AgentPlan }>()

const ROLE_LABEL: Record<string, string> = {
  rag_retrieve: 'Tìm tài liệu',
  hr_lookup: 'Tra cứu HR',
  synthesize_recommend: 'Tổng hợp & khuyến nghị',
  analyze: 'Phân tích',
  critic: 'Kiểm chứng',
}
const ROLE_ICON: Record<string, any> = {
  rag_retrieve: FileSearch,
  hr_lookup: Database,
  synthesize_recommend: Sparkles,
  analyze: Lightbulb,
  critic: ShieldCheck,
}

// Gom step theo level = độ sâu DAG (max chain depends_on). Cùng level -> song song.
const levels = computed(() => {
  const byId = new Map(props.plan.steps.map(s => [s.id, s]))
  const depthCache = new Map<number, number>()
  function depth(id: number): number {
    if (depthCache.has(id)) return depthCache.get(id)!
    const s = byId.get(id)
    const d = !s || !s.depends_on?.length ? 0 : 1 + Math.max(...s.depends_on.map(depth))
    depthCache.set(id, d)
    return d
  }
  const groups: Record<number, typeof props.plan.steps> = {}
  for (const s of props.plan.steps) {
    const d = depth(s.id)
    ;(groups[d] ??= []).push(s)
  }
  return Object.keys(groups).map(Number).sort((a, b) => a - b).map(d => groups[d])
})
</script>

<template>
  <div class="space-y-1.5">
    <div
      v-for="(group, gi) in levels"
      :key="gi"
      class="grid gap-1.5"
      :style="{ gridTemplateColumns: `repeat(${Math.min(group.length, 3)}, minmax(0, 1fr))` }"
    >
      <div
        v-for="s in group"
        :key="s.id"
        class="flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-[11.5px] transition-colors"
        :class="[
          s.status === 'running' ? 'border-blue-300 bg-blue-50/70 dark:border-blue-500/30 dark:bg-blue-500/10'
          : s.status === 'error' ? 'border-red-200 bg-red-50/50 dark:border-red-500/20 dark:bg-red-500/5'
          : s.status === 'ok' || s.status === 'no_info' ? 'border-emerald-100 bg-emerald-50/40 dark:border-emerald-500/15 dark:bg-emerald-500/5'
          : 'border-slate-100 bg-slate-50/60 dark:border-white/5 dark:bg-white/[0.03]',
        ]"
      >
        <component :is="ROLE_ICON[s.role] ?? FileSearch" class="h-3.5 w-3.5 shrink-0 text-blue-500" />
        <span class="flex-1 truncate font-medium text-slate-700 dark:text-foreground/80">
          {{ ROLE_LABEL[s.role] ?? s.role }}
        </span>
        <Loader2 v-if="s.status === 'running'" class="h-3.5 w-3.5 shrink-0 animate-spin text-blue-400" />
        <CheckCircle2 v-else-if="s.status === 'ok' || s.status === 'no_info'" class="h-3.5 w-3.5 shrink-0 text-emerald-500" />
        <XCircle v-else-if="s.status === 'error'" class="h-3.5 w-3.5 shrink-0 text-red-400" />
        <Circle v-else class="h-3 w-3 shrink-0 text-slate-300 dark:text-muted-foreground/40" />
      </div>
    </div>
  </div>
</template>
