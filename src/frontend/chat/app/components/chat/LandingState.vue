<script setup lang="ts">
import { computed } from 'vue'
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
  <div
    class="relative flex flex-col items-center justify-center text-center pt-8"
    style="contain: content"
  >
    <!-- Nền ánh sáng trắng-xanh kiểu Gemini -->
    <div
      class="pointer-events-none fixed inset-0 -z-10 landing-aura"
      aria-hidden="true"
    />

    <div class="mb-6 relative">
      <!-- Quầng sáng xanh tĩnh, đồng bộ accent với aura (bỏ pulse/bounce ồn) -->
      <div
        class="pointer-events-none absolute inset-0 rounded-full"
        style="background: radial-gradient(circle, rgba(59, 130, 246, 0.14) 0%, transparent 70%);"
        aria-hidden="true"
      />
      <div class="relative z-10 flex h-20 w-20 items-center justify-center">
        <OctopusLogo :size="64" class="saturate-100" />
      </div>
    </div>

    <!-- Câu chào động + tên người dùng -->
    <h1 class="landing-greeting text-3xl sm:text-4xl font-semibold tracking-tight">
      {{ greeting }}
    </h1>

    <p class="mt-3 text-sm font-medium text-slate-400 dark:text-muted-foreground">
      VSF's Internal AI Assistant
    </p>
  </div>
</template>

<style scoped>
/* Nền trắng-xanh kiểu Gemini: phủ kín toàn trang, xanh đậm ở giữa loang ra mép */
.landing-aura {
  background:
    radial-gradient(
      ellipse 90% 70% at 50% 40%,
      rgba(59, 130, 246, 0.45) 0%,
      rgba(96, 165, 250, 0.32) 28%,
      rgba(147, 197, 253, 0.20) 50%,
      rgba(191, 219, 254, 0.10) 70%,
      rgba(239, 246, 255, 0.04) 100%
    ),
    linear-gradient(180deg, #f0f6ff 0%, #ffffff 100%);
  animation: aura-breathe 8s ease-in-out infinite;
}

@keyframes aura-breathe {
  0%,
  100% {
    opacity: 0.85;
    transform: scale(1);
  }
  50% {
    opacity: 1;
    transform: scale(1.04);
  }
}

/* Chữ chào màu xanh-slate gradient nhẹ */
.landing-greeting {
  background: linear-gradient(180deg, #1e293b 0%, #334155 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

:global(.dark) .landing-greeting {
  background: linear-gradient(180deg, #e2e8f0 0%, #cbd5e1 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

:global(.dark) .landing-aura {
  background: radial-gradient(
    ellipse 70% 55% at 50% 42%,
    rgba(59, 130, 246, 0.22) 0%,
    rgba(37, 99, 235, 0.12) 35%,
    rgba(30, 58, 138, 0.05) 60%,
    transparent 80%
  );
}

@media (prefers-reduced-motion: reduce) {
  .landing-aura {
    animation: none;
  }
}
</style>
