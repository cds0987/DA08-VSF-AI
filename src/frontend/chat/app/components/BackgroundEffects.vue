<template>
  <!-- Nguồn nền DUY NHẤT của shell chat: aura xanh tĩnh kiểu Gemini.
       Tĩnh hoàn toàn (không animation) -> 0 chi phí repaint/frame, mượt cả khi không có GPU.
       Neo absolute inset-0 ở tầng layout (ngoài <main>) nên không dính bẫy contain/fixed. -->
  <div class="bg-aura" aria-hidden="true" />
</template>

<style scoped>
.bg-aura {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  contain: strict;
  /* Light: tô base xanh-trắng liền mạch + quầng xanh giữa loang đều ra mép (transparent mềm) */
  background:
    radial-gradient(
      ellipse 90% 70% at 50% 38%,
      rgba(59, 130, 246, 0.34) 0%,
      rgba(96, 165, 250, 0.22) 28%,
      rgba(147, 197, 253, 0.12) 52%,
      transparent 72%
    ),
    linear-gradient(180deg, #eef5ff 0%, var(--background) 62%);
}

:global(.dark) .bg-aura {
  /* Dark: quầng dịu hơn, base = đúng token --background nên không lộ mép/đường nối */
  background:
    radial-gradient(
      ellipse 90% 70% at 50% 38%,
      rgba(59, 130, 246, 0.16) 0%,
      rgba(37, 99, 235, 0.09) 34%,
      rgba(30, 58, 138, 0.05) 56%,
      transparent 78%
    ),
    var(--background);
}
</style>
