<script setup lang="ts">
import { Moon, Sun, Monitor, X } from '@lucide/vue'
import { useTheme, type Theme } from '~/composables/useTheme'

const { theme, setTheme } = useTheme()

const themes: { value: Theme; label: string; icon: any }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]
</script>

<template>
  <DialogContent class="sm:max-w-[425px] bg-white dark:bg-card border-slate-200 dark:border-border">
    <DialogHeader>
      <DialogTitle class="text-slate-900 dark:text-foreground">Settings</DialogTitle>
      <DialogDescription class="text-slate-500 dark:text-muted-foreground">
        Manage your application preferences.
      </DialogDescription>
    </DialogHeader>

    <div class="py-6">
      <div class="flex items-center justify-between">
        <div class="space-y-1">
          <h4 class="text-sm font-medium leading-none text-slate-900 dark:text-foreground">Appearance</h4>
          <p class="text-sm text-slate-500 dark:text-muted-foreground">
            Customize how the chat looks on your device.
          </p>
        </div>
      </div>

      <div class="mt-4 grid grid-cols-3 gap-2">
        <button
          v-for="item in themes"
          :key="item.value"
          @click="setTheme(item.value)"
          :class="[
            'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 p-3 transition-all',
            theme === item.value
              ? 'border-blue-600 bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400'
              : 'border-slate-100 bg-white text-slate-500 hover:bg-slate-50 dark:border-border dark:bg-muted dark:text-muted-foreground dark:hover:bg-accent'
          ]"
        >
          <component :is="item.icon" class="h-5 w-5" />
          <span class="text-xs font-medium">{{ item.label }}</span>
        </button>
      </div>
    </div>
  </DialogContent>
</template>
