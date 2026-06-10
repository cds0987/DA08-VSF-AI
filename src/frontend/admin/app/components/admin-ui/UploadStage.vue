<script setup lang="ts">
import { cn } from '~/lib/utils'

interface Props {
  label: string
  value: number
  failed?: boolean
}

defineProps<Props>()
</script>

<template>
  <div>
    <div class="mb-1 flex items-center justify-between text-[11px] text-muted-foreground">
      <span>{{ label }}</span>
      <span class="tabular-nums">{{ value }}%</span>
    </div>
    <div class="h-1.5 overflow-hidden rounded-full bg-muted">
      <div
        :class="cn(
          'h-full transition-all',
          failed ? 'bg-destructive' : value === 100 ? 'bg-emerald-500' : 'bg-primary'
        )"
        :style="{ width: `${value}%` }"
      />
    </div>
  </div>
</template>
