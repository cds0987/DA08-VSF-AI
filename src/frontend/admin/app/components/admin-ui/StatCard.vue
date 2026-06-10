<script setup lang="ts">
import { cn } from '~/lib/utils'

interface Props {
  label: string
  value: string | number
  delta?: string
  hint?: string
  intent?: 'neutral' | 'success' | 'warning' | 'error' | 'info'
}

const props = withDefaults(defineProps<Props>(), {
  intent: 'neutral'
})

const intentClass = computed(() => {
  return {
    neutral: 'text-muted-foreground',
    success: 'text-emerald-600',
    warning: 'text-amber-600',
    error: 'text-destructive',
    info: 'text-blue-600',
  }[props.intent]
})
</script>

<template>
  <div class="rounded-lg border border-border bg-card p-4 shadow-xs transform-gpu">
    <div class="flex items-center justify-between">
      <span class="text-[11.5px] font-medium uppercase tracking-wide text-muted-foreground">
        {{ label }}
      </span>
      <span v-if="$slots.icon" :class="cn('text-muted-foreground', intentClass)">
        <slot name="icon" />
      </span>
    </div>
    <div class="mt-2 flex items-baseline gap-2">
      <span class="text-[26px] font-semibold tracking-tight text-foreground tabular-nums">
        {{ value }}
      </span>
      <span v-if="delta" :class="cn('text-[12px] font-medium', intentClass)">
        {{ delta }}
      </span>
    </div>
    <p v-if="hint" class="mt-1 text-[12px] text-muted-foreground">{{ hint }}</p>
  </div>
</template>
