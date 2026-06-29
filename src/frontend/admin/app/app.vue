<script setup lang="ts">
import { useTheme } from '~/composables/useTheme'

const route = useRoute()
const { initTheme, applyTheme } = useTheme()

// Tiêu đề tab theo trang (vd /documents -> "Documents"), ngang với favicon octopus.
// Map theo segment đầu để các trang chi tiết (/documents/:id) vẫn ra đúng tên mục.
const SEGMENT_TITLES: Record<string, string> = {
  documents: 'Documents',
  upload: 'Upload Center',
  audit: 'Audit Logs',
  employees: 'Employee Management',
  login: 'Login',
}
const pageTitle = computed(() => {
  const seg = route.path.split('/')[1]
  if (!seg) return 'Dashboard'
  return SEGMENT_TITLES[seg] ?? seg.charAt(0).toUpperCase() + seg.slice(1)
})
useHead({
  title: pageTitle,
  titleTemplate: (title) => title || 'FeatureMind',
})
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
