<script setup lang="ts">
import { useSessionStore } from '~/stores/session'

const session = useSessionStore()
const route = useRoute()
const isLoginPage = computed(() => route.path === '/login')
</script>

<template>
  <div v-if="isLoginPage || !session.user">
    <slot />
  </div>
  <div
    v-else
    class="flex h-dvh w-full overflow-hidden relative bg-background text-foreground transition-colors duration-300"
  >
    <BackgroundEffects />
    <AppShell />
    <main
      class="flex min-w-0 flex-1 flex-col overflow-hidden relative z-10 transform-gpu"
      style="contain: content; will-change: transform"
    >
      <slot />
    </main>
  </div>
</template>

<style>
html,
body,
#__nuxt {
  height: 100%;
  margin: 0;
  padding: 0;
  overflow: hidden;
}
</style>
