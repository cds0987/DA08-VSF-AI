<script setup lang="ts">
import { Monitor, Moon, Sun } from '@lucide/vue'
import { useTheme, type Theme } from '~/composables/useTheme'

const { theme, setTheme } = useTheme()

const themes: { value: Theme; label: string; icon: any }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]
</script>

<template>
  <DialogContent class="sm:max-w-[425px]" @close-auto-focus.prevent>
    <DialogHeader>
      <DialogTitle>Settings</DialogTitle>
      <DialogDescription>
        Manage your admin console preferences.
      </DialogDescription>
    </DialogHeader>

    <div class="py-4">
      <div class="space-y-1">
        <h4 class="text-sm font-medium leading-none text-foreground">Appearance</h4>
        <p class="text-sm text-muted-foreground">
          Customize how the admin console looks on your device.
        </p>
      </div>

      <div class="mt-4 grid grid-cols-3 gap-2">
        <button
          v-for="item in themes"
          :key="item.value"
          type="button"
          :aria-pressed="theme === item.value"
          :class="[
            'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 p-3 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring',
            theme === item.value
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-border bg-card text-muted-foreground hover:bg-accent hover:text-foreground',
          ]"
          @click="setTheme(item.value)"
        >
          <component :is="item.icon" class="h-5 w-5" />
          <span class="text-xs font-medium">{{ item.label }}</span>
        </button>
      </div>
    </div>
  </DialogContent>
</template>
