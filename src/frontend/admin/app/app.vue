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
  <!-- disable-hoverable-content: tooltip đóng NGAY khi rời trigger -> tránh tooltip giả/tích tụ
       khi con trỏ lướt qua icon sidebar thu gọn (đồng bộ chat, fix phantom-hover). -->
  <TooltipProvider :delay-duration="0" :disable-hoverable-content="true">
    <NuxtLayout>
      <NuxtRouteAnnouncer />
      <NuxtPage />
      <Toaster position="top-right" rich-colors />
    </NuxtLayout>
  </TooltipProvider>
</template>
