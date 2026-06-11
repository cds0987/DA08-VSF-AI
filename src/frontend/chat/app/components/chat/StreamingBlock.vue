<script setup lang="ts">
defineProps<{
  text: string
}>()
</script>

<template>
  <div class="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-5 pb-5 pt-4 shadow-sm">
    <p class="whitespace-pre-wrap text-[16px] font-medium leading-relaxed text-slate-900 dark:text-slate-100 [overflow-wrap:anywhere] [word-break:break-word]">
      {{ text }}
      <span class="ml-0.5 inline-flex h-5 items-end align-middle">
        <span class="streaming-cursor h-4 w-[2px] rounded-full bg-blue-500 dark:bg-blue-400" />
      </span>
    </p>
  </div>
</template>

<style scoped>
.streaming-cursor {
  animation: streaming-blink 0.9s steps(1, end) infinite;
  box-shadow: 0 0 0.65rem rgb(59 130 246 / 0.35);
}

@keyframes streaming-blink {
  0%,
  45% {
    opacity: 1;
  }

  55%,
  100% {
    opacity: 0;
  }
}
</style>
