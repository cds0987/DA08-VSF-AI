<script setup lang="ts">
import OctopusLogo from '~/components/OctopusLogo.vue'
</script>

<template>
  <div
    class="flex flex-col items-center justify-center text-center pt-8"
    style="contain: content"
  >
    <div class="mb-6 relative group">
      <div
        class="absolute inset-0 rounded-full animate-pulse"
        style="
          background: radial-gradient(circle, rgba(239, 68, 68, 0.15) 0%, transparent 70%);
          will-change: transform, opacity;
          transform: translate3d(0, 0, 0);
          backface-visibility: hidden;
          perspective: 1000px;
        "
      />

      <div
        class="relative z-10 flex h-20 w-20 items-center justify-center animate-bounce"
        style="
          animation-duration: 3s;
          will-change: transform, filter;
          transform: translate3d(0, 0, 0);
          backface-visibility: hidden;
          perspective: 1000px;
        "
      >
        <OctopusLogo
          :size="64"
          class="saturate-100"
          style="transform: translate3d(0, 0, 0); will-change: transform;"
        />
      </div>
    </div>
    <div class="flex flex-col gap-1">
      <p class="text-lg font-medium text-slate-500 dark:text-muted-foreground">
        VSF's Internal AI Assistant
      </p>
    </div>
    <p class="mt-6 text-base text-slate-400 dark:text-muted-foreground">How can I help you today?</p>
  </div>
</template>
