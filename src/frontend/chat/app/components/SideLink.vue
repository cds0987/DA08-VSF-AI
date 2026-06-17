<script setup lang="ts">
import { cn } from '~/lib/utils'

interface NavItem {
  label: string
  to: string
  icon: any
}

const props = defineProps<{
  item: NavItem
  isCollapsed: boolean
  disableTooltip?: boolean
}>()

const route = useRoute()

const active = computed(() => {
  return route.path === props.item.to || (props.item.to !== '/' && route.path.startsWith(props.item.to))
})
</script>

<template>
  <Tooltip>
    <TooltipTrigger asChild>
      <NuxtLink
        :to="item.to"
        :class="cn(
          'flex items-center rounded-md text-[13px] font-semibold overflow-hidden cursor-pointer shrink-0 h-9 transition-all w-full justify-start',
          active
            ? 'bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400 shadow-sm ring-1 ring-blue-100 dark:ring-blue-900/50'
            : 'text-slate-600 dark:text-muted-foreground hover:bg-slate-100 dark:hover:bg-sidebar-accent hover:text-slate-900 dark:hover:text-sidebar-accent-foreground',
        )"
      >
        <div class="flex h-9 w-[64px] items-center justify-center shrink-0">
          <component 
            :is="item.icon" 
            :class="cn(
              'h-5 w-5 shrink-0',
              active ? 'text-blue-600 dark:text-blue-400' : 'text-slate-500 dark:text-muted-foreground'
            )" 
          />
        </div>
        <span
          class="whitespace-nowrap transition-opacity duration-300"
          :class="isCollapsed ? 'opacity-0' : 'opacity-100'"
        >
          {{ item.label }}
        </span>
      </NuxtLink>
    </TooltipTrigger>
    <TooltipContent
      v-if="isCollapsed && !disableTooltip"
      side="right"
      class="bg-slate-900 text-[11px] font-medium text-white dark:bg-slate-100 dark:text-slate-900 border-none shadow-md"
    >
      {{ item.label }}
    </TooltipContent>
  </Tooltip>
</template>
