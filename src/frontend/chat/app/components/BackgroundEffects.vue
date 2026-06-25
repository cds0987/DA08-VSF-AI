<template>
  <!-- Nền phẳng kiểu DeepSeek: light=trắng, dark=đen — bám đúng token --background.
       Tĩnh hoàn toàn, ~0 chi phí/frame. Dấu ấn brand (quầng đỏ) nằm ở LandingState,
       chỉ hiện màn chào -> màn chat phẳng tuyệt đối. -->
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
