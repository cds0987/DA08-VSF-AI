<script setup lang="ts">
import { computed } from 'vue'
import { Sparkles } from '@lucide/vue'
import OctopusLogo from '~/components/OctopusLogo.vue'
import { useSessionStore } from '~/stores/session'

const session = useSessionStore()

// Lấy tên gọi (given name) — với tên tiếng Việt thường là từ cuối cùng.
const firstName = computed(() => {
  const full = session.user?.name?.trim()
  if (!full) return ''
  const parts = full.split(/\s+/)
  return parts[parts.length - 1]
})

// Bộ câu chào động kiểu Gemini. {name} sẽ được thay bằng tên người dùng.
const greetingsWithName = [
  'Tiếp theo sẽ là gì, {name}?',
  'Hôm nay mình làm gì nào, {name}?',
  'Bắt đầu từ đâu nhỉ, {name}?',
  'Rất vui được gặp lại, {name}!',
  'Có điều gì cần khám phá không, {name}?',
  'Sẵn sàng khi bạn cần, {name}.',
  'Chào {name}, mình cùng bắt đầu nhé?',
]

const greetingsNoName = [
  'Tiếp theo sẽ là gì?',
  'Hôm nay mình làm gì nào?',
  'Bắt đầu từ đâu nhỉ?',
  'Rất vui được gặp bạn!',
  'Có điều gì cần khám phá không?',
  'Sẵn sàng khi bạn cần.',
]

// Chọn ngẫu nhiên mỗi lần mount màn hình chào.
const greeting = computed(() => {
  const pool = firstName.value ? greetingsWithName : greetingsNoName
  const pick = pool[Math.floor(Math.random() * pool.length)] ?? pool[0]!
  return firstName.value ? pick.replace('{name}', firstName.value) : pick
})
</script>

<template>
  <div class="relative isolate flex flex-col items-center justify-center text-center pt-8">
    <!-- Nền phẳng (trắng/đen) do BackgroundEffects.vue ở tầng layout đảm nhiệm.
         Dấu ấn brand: 1 quầng đỏ mờ TĨNH sau logo+greeting (chỉ màn chào). -->
    <div class="brand-halo pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2" aria-hidden="true" />

    <!-- Octopus + sparkle lấp lánh (glow dịu tĩnh, không bounce/pulse ồn) -->
    <div class="mb-6 relative">
      <div
        class="pointer-events-none absolute inset-0 rounded-full"
        style="background: radial-gradient(circle, rgba(239, 68, 68, 0.16) 0%, transparent 70%);"
        aria-hidden="true"
      />

      <Sparkles class="sparkle sparkle-1 absolute h-4 w-4 text-rose-300" style="top: -6px; right: -10px;" />
      <Sparkles class="sparkle sparkle-2 absolute h-3 w-3 text-pink-300" style="bottom: 4px; left: -14px;" />
      <Sparkles class="sparkle sparkle-3 absolute h-2.5 w-2.5 text-rose-200" style="top: 8px; left: -4px;" />
      <Sparkles class="sparkle sparkle-4 absolute h-3 w-3 text-pink-200" style="bottom: -6px; right: 2px;" />

      <div class="relative z-10 flex h-20 w-20 items-center justify-center">
        <OctopusLogo :size="64" class="saturate-100" />
      </div>
    </div>

    <!-- Câu chào động + tên người dùng -->
    <h1 class="landing-greeting text-3xl sm:text-4xl font-semibold tracking-tight">
      {{ greeting }}
    </h1>

    <!-- Subtitle với gạch trang trí hai bên -->
    <div class="mt-3 flex items-center justify-center gap-3">
      <span class="h-px w-8 bg-gradient-to-r from-transparent to-slate-300 dark:to-white/20" />
      <p class="text-sm font-medium text-slate-400 dark:text-muted-foreground">
        VSF's Internal AI Assistant
      </p>
      <span class="h-px w-8 bg-gradient-to-l from-transparent to-slate-300 dark:to-white/20" />
    </div>
    <div class="mt-2 flex items-center justify-center gap-1.5">
      <span class="h-1.5 w-1.5 rounded-full bg-rose-400/70" />
      <span class="h-1.5 w-1.5 rounded-full bg-blue-400/70" />
    </div>
  </div>
</template>

<style scoped>
/* Quầng đỏ brand TĨNH sau logo+greeting — dấu ấn riêng, nền vẫn phẳng.
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
  /* Trên nền đen quầng đỏ nổi hơn -> hue rose dịu, vẫn rất nhẹ */
  background: radial-gradient(
    circle,
    rgba(244, 63, 94, 0.16) 0%,
    rgba(244, 63, 94, 0.06) 40%,
    transparent 72%
  );
}

/* Chữ chào gradient slate */
.landing-greeting {
  background: linear-gradient(180deg, #1e293b 0%, #334155 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

/* Sparkle lấp lánh quanh octopus */
.sparkle {
  z-index: 20;
  animation: twinkle 2.4s ease-in-out infinite;
}
.sparkle-2 {
  animation-delay: 0.6s;
}
.sparkle-3 {
  animation-delay: 1.2s;
}
.sparkle-4 {
  animation-delay: 1.8s;
}

@keyframes twinkle {
  0%,
  100% {
    opacity: 0.3;
    transform: scale(0.8);
  }
  50% {
    opacity: 1;
    transform: scale(1.15);
  }
}

:global(.dark) .landing-greeting {
  background: linear-gradient(180deg, #e2e8f0 0%, #cbd5e1 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

@media (prefers-reduced-motion: reduce) {
  .sparkle {
    animation: none;
  }
}
</style>
