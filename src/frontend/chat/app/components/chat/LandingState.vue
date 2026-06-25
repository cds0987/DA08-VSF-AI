<script setup lang="ts">
import OctopusLogo from '~/components/OctopusLogo.vue'
</script>

<template>
  <div class="relative isolate flex flex-col items-center justify-center text-center pt-8">
    <!-- Nền phẳng (trắng/đen) do BackgroundEffects.vue ở tầng layout đảm nhiệm.
         Dấu ấn brand: 1 quầng đỏ mờ TĨNH sau logo+tiêu đề (chỉ màn chào). -->
    <div class="brand-halo pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2" aria-hidden="true" />

    <!-- Logo agent (glow đỏ dịu TĨNH, không nhấp nháy) -->
    <div class="mb-6 relative">
      <div
        class="pointer-events-none absolute inset-0 rounded-full"
        style="background: radial-gradient(circle, rgba(239, 68, 68, 0.16) 0%, transparent 70%);"
        aria-hidden="true"
      />
      <div class="relative z-10 flex h-20 w-20 items-center justify-center">
        <OctopusLogo :size="64" class="saturate-100" />
      </div>
    </div>

    <!-- Tiêu đề chủ đạo: tương phản mạnh, rõ ở cả light & dark -->
    <h1 class="landing-title text-3xl sm:text-4xl font-semibold tracking-tight">
      VSF's Internal AI Assistant
    </h1>

    <!-- Chấm accent brand (rose + blue) — dấu ấn nhỏ, tĩnh -->
    <div class="mt-4 flex items-center justify-center gap-1.5">
      <span class="h-1.5 w-1.5 rounded-full bg-rose-400/80" />
      <span class="h-1.5 w-1.5 rounded-full bg-blue-400/80" />
    </div>
  </div>
</template>

<style scoped>
/* Quầng đỏ brand TĨNH sau logo+tiêu đề — dấu ấn riêng, nền vẫn phẳng.
   ~560px, mờ dần ra trong suốt; static -> 0 chi phí/frame. */
.brand-halo {
  width: 560px;
  height: 560px;
  border-radius: 9999px;
  background: radial-gradient(
    circle,
    rgba(239, 68, 68, 0.12) 0%,
    rgba(239, 68, 68, 0.05) 38%,
    transparent 70%
  );
}
:global(.dark) .brand-halo {
  background: radial-gradient(
    circle,
    rgba(244, 63, 94, 0.16) 0%,
    rgba(244, 63, 94, 0.06) 40%,
    transparent 72%
  );
}

/* Tiêu đề: gradient tương phản cao — đậm trên nền trắng */
.landing-title {
  background: linear-gradient(180deg, #0f172a 0%, #334155 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
/* Dark: sáng rõ trên nền đen */
:global(.dark) .landing-title {
  background: linear-gradient(180deg, #f8fafc 0%, #cbd5e1 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
</style>
