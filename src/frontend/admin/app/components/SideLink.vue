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
  <Tooltip :disabled="disableTooltip" :ignore-non-keyboard-focus="true">
    <TooltipTrigger asChild>
      <NuxtLink
        :to="item.to"
        :class="cn(
          'flex items-center rounded-lg text-sm font-semibold overflow-hidden cursor-pointer shrink-0 h-9 transition-all w-full justify-start text-slate-900 dark:text-sidebar-foreground',
          active
            ? 'bg-slate-100 dark:bg-sidebar-accent'
            : 'hover:bg-slate-100 dark:hover:bg-sidebar-accent',
        )"
      >
        <div class="flex h-9 items-center justify-center shrink-0" :class="isCollapsed ? 'w-full' : 'w-[64px]'">
          <component
            :is="item.icon"
            :class="cn(
              'h-5 w-5 shrink-0',
              active ? 'text-slate-700 dark:text-sidebar-accent-foreground' : 'text-slate-900 dark:text-white'
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
      v-if="isCollapsed"
      side="right"
      class="bg-slate-900 text-[11px] font-medium text-white dark:bg-slate-100 dark:text-slate-900 border-none shadow-md"
    >
      {{ item.label }}
    </TooltipContent>
  </Tooltip>
</template>
