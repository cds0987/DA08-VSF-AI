<script setup lang="ts">
import { Sparkles } from '@lucide/vue'
import { cn } from '~/lib/utils'
import type { PipelineStage } from '~/types'

interface Props {
  stage: number
  stages: PipelineStage[]
}

const props = defineProps<Props>()
</script>

<template>
  <div class="rounded-xl border border-slate-200 dark:border-border bg-white dark:bg-chat-response p-4 shadow-sm dark:shadow-none">
    <div class="mb-3 flex items-center gap-2 text-[12px] font-medium text-slate-800 dark:text-foreground">
      <Sparkles class="h-3.5 w-3.5 text-blue-500" />
      Retrieval pipeline
    </div>
    <div class="space-y-1.5">
      <div
        v-for="(s, i) in stages"
        :key="s.label"
        :class="cn(
          'flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[12.5px]',
          i === stage && 'bg-blue-50 dark:bg-blue-500/10 text-slate-900 dark:text-foreground',
          i < stage && 'text-slate-500 dark:text-muted-foreground',
          i > stage && 'text-slate-400 dark:text-muted-foreground/70',
        )"
      >
        <span
          :class="cn(
            'flex h-5 w-5 items-center justify-center rounded-full border',
            i < stage && 'border-emerald-500/50 bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
            i === stage && 'border-blue-400 text-blue-600 shadow-[0_0_8px_rgba(37,99,235,0.2)]',
            i > stage && 'border-slate-200 dark:border-border text-slate-300 dark:text-muted-foreground/50',
          )"
        >
          <template v-if="i < stage">
            <svg
              viewBox="0 0 24 24"
              class="h-3 w-3"
              fill="none"
              stroke="currentColor"
              stroke-width="3"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </template>
          <component v-else :is="s.icon" class="h-3 w-3" />
        </span>
        <span class="flex-1">{{ s.label }}</span>
        <span v-if="i === stage" class="text-[11px] text-blue-500 animate-pulse">
          in progress…
        </span>
        <span v-if="i < stage" class="text-[11px] text-emerald-600">done</span>
      </div>
    </div>
  </div>
</template>
