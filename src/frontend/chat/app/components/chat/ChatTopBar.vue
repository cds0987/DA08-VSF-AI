<script setup lang="ts">
import { computed } from 'vue'
import { HelpCircle, Moon, Sun } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { useTheme } from '~/composables/useTheme'

const { theme, setTheme } = useTheme()

const isDark = computed(() => {
  if (theme.value === 'dark') return true
  if (theme.value === 'light') return false
  return import.meta.client && window.matchMedia('(prefers-color-scheme: dark)').matches
})

function toggleTheme() {
  setTheme(isDark.value ? 'light' : 'dark')
}

function showHelp() {
  toast.info('Trợ giúp', {
    description: 'Đặt câu hỏi về chính sách, quy trình hay kiến thức nội bộ. Tối đa 500 ký tự mỗi câu.',
  })
}
</script>

<template>
  <div class="pointer-events-none absolute inset-x-0 top-0 z-40 flex items-center justify-between px-6 py-4">
    <!-- Trạng thái hệ thống -->
    <div
      class="pointer-events-auto inline-flex items-center gap-2 rounded-full border border-slate-200/70 bg-white/70 px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm backdrop-blur-md dark:border-white/10 dark:bg-white/5 dark:text-muted-foreground"
    >
      <span class="relative flex h-2 w-2">
        <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
        <span class="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
      </span>
      Hệ thống hoạt động tốt
    </div>

    <!-- Trợ giúp + chuyển chế độ sáng/tối -->
    <div class="pointer-events-auto flex items-center gap-2">
      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded-full border border-slate-200/70 bg-white/70 px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm backdrop-blur-md transition-colors hover:bg-white dark:border-white/10 dark:bg-white/5 dark:text-muted-foreground dark:hover:bg-white/10"
        @click="showHelp"
      >
        <HelpCircle class="h-3.5 w-3.5" />
        Trợ giúp
      </button>
      <button
        type="button"
        :aria-label="isDark ? 'Chuyển sang chế độ sáng' : 'Chuyển sang chế độ tối'"
        class="inline-flex h-8 w-8 items-center justify-center rounded-full border border-slate-200/70 bg-white/70 text-slate-600 shadow-sm backdrop-blur-md transition-colors hover:bg-white dark:border-white/10 dark:bg-white/5 dark:text-muted-foreground dark:hover:bg-white/10"
        @click="toggleTheme"
      >
        <Moon v-if="!isDark" class="h-4 w-4" />
        <Sun v-else class="h-4 w-4" />
      </button>
    </div>
  </div>
</template>
