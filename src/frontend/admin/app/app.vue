<script setup lang="ts">
import { useTheme } from '~/composables/useTheme'

const route = useRoute()
const { initTheme, applyTheme } = useTheme()
let stopRouteWatch: (() => void) | null = null

onMounted(() => {
  initTheme()
  stopRouteWatch = watch(
    () => route.path,
    () => applyTheme(),
  )
})

onBeforeUnmount(() => {
  stopRouteWatch?.()
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
