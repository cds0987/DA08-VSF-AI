<script setup lang="ts">
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
