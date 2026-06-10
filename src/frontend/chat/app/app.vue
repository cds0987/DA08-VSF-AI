<script setup lang="ts">
import { useSessionStore } from './stores/session'
import { useNotificationStore } from './stores/notifications'

const session = useSessionStore()
const notifications = useNotificationStore()
let stopSessionWatch: (() => void) | null = null

onMounted(() => {
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
