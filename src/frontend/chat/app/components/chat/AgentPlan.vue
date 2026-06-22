<script setup lang="ts">
// Hiển thị KẾ HOẠCH orchestrator-workers: các node theo LEVEL (depends_on). Node cùng level
// chạy SONG SONG -> render cùng 1 hàng (nhiều cột) để user thấy subagents chạy song song.
// (v2 2026-06-19: force-rebuild FE image để deploy UI mới — xem orchestration.py marker.)
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
  <!-- Sub-step trong timeline: mỗi level 1 hàng (cùng level = song song), item gọn không viền nặng. -->
  <div class="space-y-1">
    <div
      v-for="(group, gi) in levels"
      :key="gi"
      class="grid gap-x-3 gap-y-1"
      :style="{ gridTemplateColumns: `repeat(${Math.min(group.length, 3)}, minmax(0, 1fr))` }"
    >
      <div
        v-for="s in group"
        :key="s.id"
        class="relative flex items-center gap-1.5 pl-4 text-[11px]"
      >
        <span
          aria-hidden="true"
          class="absolute left-0.5 top-[7px] h-1.5 w-1.5 rounded-full"
          :class="[
            s.status === 'running' ? 'bg-blue-400'
            : s.status === 'error' ? 'bg-red-400'
            : s.status === 'ok' || s.status === 'no_info' ? 'bg-emerald-400'
            : 'bg-slate-300 dark:bg-white/25',
          ]"
        />
        <component :is="ROLE_ICON[s.role] ?? FileSearch" class="h-3.5 w-3.5 shrink-0 text-slate-400 dark:text-muted-foreground" />
        <span class="flex-1 truncate font-medium text-slate-700 dark:text-foreground/80">
          {{ ROLE_LABEL[s.role] ?? s.role }}
        </span>
        <Loader2 v-if="s.status === 'running'" class="h-3 w-3 shrink-0 animate-spin text-blue-400" />
        <CheckCircle2 v-else-if="s.status === 'ok' || s.status === 'no_info'" class="h-3 w-3 shrink-0 text-emerald-500" />
        <XCircle v-else-if="s.status === 'error'" class="h-3 w-3 shrink-0 text-red-400" />
        <Circle v-else class="h-3 w-3 shrink-0 text-slate-300 dark:text-muted-foreground/40" />
      </div>
    </div>
  </div>
</template>
