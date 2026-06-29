<script setup lang="ts">
import type { Component } from 'vue'
import {
  Info,
  Monitor,
  Moon,
  Settings,
  Sun,
  User,
} from '@lucide/vue'
import { useTheme, type Theme } from '~/composables/useTheme'
import { useSessionStore } from '~/stores/session'

type SettingsSection = 'general' | 'profile' | 'about'

const { theme, setTheme } = useTheme()
const session = useSessionStore()
const activeSection = ref<SettingsSection>('general')

const sections: { value: SettingsSection; label: string; icon: Component }[] = [
  { value: 'general', label: 'General', icon: Settings },
  { value: 'profile', label: 'Profile', icon: User },
  { value: 'about', label: 'About', icon: Info },
]

const themes: { value: Theme; label: string; icon: Component }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]

function displayValue(value: string | boolean | null | undefined) {
  if (typeof value === 'boolean') return value ? 'Active' : 'Inactive'
  const normalized = value?.toString().trim()
  return normalized || '-'
}

const profileRows = computed(() => [
  { label: 'Email address', value: displayValue(session.user?.email) },
  { label: 'Name', value: displayValue(session.user?.name) },
  { label: 'Role', value: displayValue(session.user?.role) },
  { label: 'Department', value: displayValue(session.user?.department) },
  { label: 'Status', value: displayValue(session.user?.is_active) },
])

const aboutRows = computed(() => [
  { label: 'Product', value: 'FeatureMind' },
  { label: 'Purpose', value: 'Admin console for document and employee management.' },
  { label: 'Signed in role', value: displayValue(session.user?.role) },
])
</script>

<template>
  <DialogContent
    class="h-[min(640px,calc(100dvh-2rem))] w-[min(calc(100vw-2rem),760px)] overflow-hidden rounded-[28px] border-slate-200 bg-white p-0 shadow-2xl shadow-slate-950/10 sm:max-w-[760px] dark:border-border dark:bg-card dark:shadow-black/35"
    @close-auto-focus.prevent
  >
    <div class="grid h-full grid-cols-1 overflow-hidden sm:grid-cols-[184px_1fr]">
      <aside
        class="flex min-h-0 flex-col border-b border-slate-200 bg-slate-50/80 p-3 sm:border-b-0 sm:border-r dark:border-border dark:bg-muted/30"
      >
        <DialogHeader class="px-1 pb-3 pt-1 text-left">
          <DialogTitle class="text-base font-semibold text-slate-900 dark:text-foreground">Settings</DialogTitle>
          <DialogDescription class="sr-only">
            Manage FeatureMind preferences and account information.
          </DialogDescription>
        </DialogHeader>

        <nav class="flex gap-1 overflow-x-auto sm:flex-col sm:overflow-visible" aria-label="Settings sections">
          <button
            v-for="section in sections"
            :key="section.value"
            type="button"
            class="flex h-10 shrink-0 cursor-pointer items-center gap-2 rounded-xl px-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 sm:w-full"
            :class="activeSection === section.value
              ? 'bg-slate-200 text-slate-900 dark:bg-accent dark:text-foreground'
              : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-muted-foreground dark:hover:bg-accent/60 dark:hover:text-foreground'"
            @click="activeSection = section.value"
          >
            <component :is="section.icon" class="h-4 w-4 shrink-0" />
            <span>{{ section.label }}</span>
          </button>
        </nav>
      </aside>

      <section class="min-h-0 overflow-y-auto px-5 py-6 sm:px-10 sm:py-8">
        <div v-if="activeSection === 'general'" class="space-y-3">
          <h3 class="text-sm font-semibold text-slate-900 dark:text-foreground">Theme</h3>
          <div class="grid grid-cols-3 gap-3">
            <button
              v-for="item in themes"
              :key="item.value"
              type="button"
              class="flex min-h-[82px] cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
              :class="theme === item.value
                ? 'border-slate-300 bg-slate-100 text-slate-900 dark:border-border dark:bg-accent dark:text-foreground'
                : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:text-slate-900 dark:border-border dark:bg-transparent dark:text-muted-foreground dark:hover:bg-accent/60 dark:hover:text-foreground'"
              @click="setTheme(item.value)"
            >
              <component :is="item.icon" class="h-5 w-5" />
              <span>{{ item.label }}</span>
            </button>
          </div>
        </div>

        <div v-else-if="activeSection === 'profile'" class="space-y-1">
          <div
            v-for="row in profileRows"
            :key="row.label"
            class="flex min-h-[58px] items-center justify-between gap-6 border-b border-slate-200 py-3 last:border-b-0 dark:border-border"
          >
            <span class="text-sm font-medium text-slate-900 dark:text-foreground">{{ row.label }}</span>
            <span class="min-w-0 max-w-[260px] truncate text-right text-sm font-medium text-slate-600 dark:text-muted-foreground">
              {{ row.value }}
            </span>
          </div>
        </div>

        <div v-else class="space-y-1">
          <div
            v-for="row in aboutRows"
            :key="row.label"
            class="flex min-h-[58px] items-center justify-between gap-6 border-b border-slate-200 py-3 last:border-b-0 dark:border-border"
          >
            <span class="text-sm font-medium text-slate-900 dark:text-foreground">{{ row.label }}</span>
            <span class="min-w-0 max-w-[300px] text-right text-sm font-medium text-slate-600 dark:text-muted-foreground">
              {{ row.value }}
            </span>
          </div>
        </div>
      </section>
    </div>
  </DialogContent>
</template>
