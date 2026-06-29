<template>
  <!-- Nền phẳng kiểu DeepSeek: light=trắng, dark=đen — bám đúng token --background.
       Tĩnh hoàn toàn, ~0 chi phí/frame. Đồng bộ 1-1 với chat/app/components/BackgroundEffects.vue. -->
  <div class="bg-flat" aria-hidden="true" />
</template>

<style scoped>
.bg-flat {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  contain: strict;
  background: var(--background);
}
</style>
