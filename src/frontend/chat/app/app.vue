<script setup lang="ts">
import { useSessionStore } from './stores/session'
import { useNotificationStore } from './stores/notifications'
import { useTheme } from './composables/useTheme'

const session = useSessionStore()
const notifications = useNotificationStore()
const route = useRoute()
const { initTheme, applyTheme } = useTheme()
let stopSessionWatch: (() => void) | null = null
let stopRouteWatch: (() => void) | null = null

onMounted(() => {
  initTheme()
  stopRouteWatch = watch(
    () => route.path,
    () => applyTheme(),
  )
  stopSessionWatch = watch(
    () => session.user,
    (user) => {
      if (user) {
        void notifications.init()
      } else {
        notifications.stop()
      }
    },
    { immediate: true },
  )
})

onBeforeUnmount(() => {
  stopRouteWatch?.()
  stopSessionWatch?.()
  notifications.stop()
})
</script>

<template>
  <TooltipProvider :delay-duration="0">
    <NuxtLayout>
      <NuxtRouteAnnouncer />
      <NuxtPage />
      <Toaster position="top-right" rich-colors />
    </NuxtLayout>
  </TooltipProvider>
</template>
