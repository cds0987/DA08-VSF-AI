<script setup lang="ts">
import { cn } from '~/lib/utils'

interface Props {
  status: string
}

const props = defineProps<Props>()

const badgeStyle = computed(() => {
  const map: Record<string, { cls: string }> = {
    indexed: { cls: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20' },
    active: { cls: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20' },
    success: { cls: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20' },
    approved: { cls: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20' },
    pending: { cls: 'bg-amber-500/15 text-amber-700 border-amber-500/30' },
    rejected: { cls: 'bg-destructive/10 text-destructive border-destructive/20' },
    cancelled: { cls: 'bg-muted text-muted-foreground border-border' },
    processing: { cls: 'bg-blue-500/10 text-blue-600 border-blue-500/20' },
    queued: { cls: 'bg-muted text-muted-foreground border-border' },
    invited: { cls: 'bg-blue-500/10 text-blue-600 border-blue-500/20' },
    failed: { cls: 'bg-destructive/10 text-destructive border-destructive/20' },
    error: { cls: 'bg-destructive/10 text-destructive border-destructive/20' },
    denied: { cls: 'bg-destructive/10 text-destructive border-destructive/20' },
    suspended: {
      cls: 'bg-amber-500/15 text-amber-700 border-amber-500/30',
    },
    // Keep PascalCase for compatibility with any legacy mock data if needed
    Indexed: { cls: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20' },
    Processing: { cls: 'bg-blue-500/10 text-blue-600 border-blue-500/20' },
    Queued: { cls: 'bg-muted text-muted-foreground border-border' },
    Failed: { cls: 'bg-destructive/10 text-destructive border-destructive/20' },
  }
  return map[props.status] ?? {
    cls: 'bg-muted text-muted-foreground border-border',
  }
})
</script>

<template>
  <span
    :class="cn(
      'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium',
      badgeStyle.cls,
    )"
  >
    <span class="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
    {{ status }}
  </span>
</template>
