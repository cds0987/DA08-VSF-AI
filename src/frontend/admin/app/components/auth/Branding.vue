<script setup lang="ts">
import { cn } from '~/lib/utils'

defineProps<{
  isLoading: boolean
}>()

const itemVariants = {
  initial: { opacity: 0, y: 15 },
  enter: {
    opacity: 1,
    y: 0,
    transition: {
      type: 'spring',
      stiffness: 70,
      damping: 14,
    },
  },
}

const bloomVariants = {
  initial: { opacity: 0.3, scale: 1 },
  enter: {
    opacity: [0.3, 0.5, 0.3],
    scale: [1, 1.05, 1],
    transition: {
      duration: 5000,
      repeat: Infinity,
      ease: 'easeInOut',
    },
  },
}

const particleVariants = (i: number) => ({
  initial: { opacity: 0, scale: 0 },
  enter: {
    opacity: [0, 0.9, 0],
    scale: [0, 1.2, 0],
    x: [0, Math.cos(i * 60 * (Math.PI / 180)) * (40 + (i % 3) * 10), 0],
    y: [0, Math.sin(i * 60 * (Math.PI / 180)) * (40 + (i % 3) * 10), 0],
    transition: {
      duration: 4000,
      delay: i * 150,
      repeat: Infinity,
      ease: 'easeInOut',
    },
  },
})

const logoRotatingVariants = {
  initial: { rotate: 0, y: 0 },
  enter: {
    rotate: 360,
    y: [0, -6, 0],
    transition: {
      rotate: { duration: 10000, repeat: Infinity, ease: 'linear' },
      y: { duration: 4000, repeat: Infinity, ease: 'easeInOut' },
    },
  },
}

const glowOpacityVariants = {
  initial: { opacity: 0.4 },
  enter: {
    opacity: [0.4, 0.7, 0.4],
    transition: { duration: 4000, repeat: Infinity, ease: 'easeInOut' },
  },
}

const textPulseVariants = {
  initial: { opacity: 0.4 },
  enter: {
    opacity: [0.4, 1, 0.4],
    transition: {
      duration: 5000,
      repeat: Infinity,
      ease: 'easeInOut',
    },
  },
}
</script>

<template>
  <div v-motion="itemVariants" class="mb-8 flex flex-col items-center justify-center text-center relative">
    <!-- Static background glow - Hardware accelerated -->
    <div
      class="absolute inset-x-0 -top-10 bottom-0 bg-gradient-to-b from-rose-500/10 via-transparent to-transparent pointer-events-none blur-2xl z-0 transform-gpu"
      style="backface-visibility: hidden; will-change: transform;"
    />

    <div
      class="mb-4 flex justify-center relative z-10"
    >
      <!-- Optimized Bloom Effect -->
      <div
        class="absolute inset-0 bg-red-600/25 rounded-full blur-2xl pointer-events-none transform-gpu"
        v-motion="bloomVariants"
        style="will-change: opacity, transform; backface-visibility: hidden;"
      />

      <!-- Optimized Particles -->
      <div
        v-for="i in 6"
        :key="`particle-${i}`"
        v-motion="particleVariants(i - 1)"
        :class="cn(
          'absolute rounded-full transform-gpu',
          (i - 1) % 2 === 0
            ? 'w-2 h-2 bg-red-500/90'
            : 'w-1.5 h-1.5 bg-rose-600/80',
        )"
        style="left: 50%; top: 50%; margin-left: -4px; margin-top: -4px; will-change: transform; backface-visibility: hidden;"
      />

      <div class="relative">
        <!-- Loading Glow -->
        <div
          v-if="isLoading"
          class="absolute inset-0 bg-red-500/30 rounded-full blur-md transform-gpu"
          v-motion
          :initial="{ opacity: 0.2 }"
          :enter="{ opacity: [0.2, 0.5, 0.2], transition: { duration: 1500, repeat: Infinity } }"
          style="will-change: opacity; backface-visibility: hidden;"
        />

        <!-- Independent Logo Glow Layer -->
        <div
          v-motion="glowOpacityVariants"
          class="absolute inset-0 rounded-full bg-red-500/20 blur-xl transform-gpu"
          style="will-change: opacity; backface-visibility: hidden;"
        />

        <!-- Main Logo Container -->
        <div
          v-motion="logoRotatingVariants"
          class="relative h-20 w-20 flex items-center justify-center rounded-full overflow-hidden transform-gpu"
          style="will-change: transform; backface-visibility: hidden;"
        >
          <img
            src="/logo.png"
            alt="FeatureMind Logo"
            width="80"
            height="80"
            class="w-full h-full object-contain saturate-150"
            style="backface-visibility: hidden;"
          />
        </div>

        <!-- Animated Border - No Box Shadow -->
        <div
          class="absolute inset-0 rounded-full border-4 border-transparent border-t-red-500/60 border-r-rose-500/60 transform-gpu"
          v-motion
          :initial="{ rotate: 0 }"
          :enter="{ rotate: 360, transition: { duration: 4000, repeat: Infinity, ease: 'linear' } }"
          style="width: 92px; height: 92px; left: -6px; top: -6px; will-change: transform; backface-visibility: hidden;"
        />
      </div>
    </div>

    <div
      class="flex flex-col items-center justify-center relative z-10"
      v-motion="itemVariants"
    >
      <div class="flex items-center justify-center gap-3">
        <OctopusLogo
          :size="32"
          class="transform-gpu"
          style="will-change: transform;"
        />
        <div class="relative">
          <h1
            class="text-4xl sm:text-5xl font-extrabold tracking-tight text-[#0f172a] relative z-10"
          >
            FeatureMind
          </h1>

          <!-- Optimized Text Pulse -->
          <h1
            v-motion="textPulseVariants"
            class="absolute inset-0 text-4xl sm:text-5xl font-extrabold tracking-tight z-20 pointer-events-none transform-gpu"
            style="
              background: linear-gradient(to bottom, #E11D48 0%, transparent 70%);
              -webkit-background-clip: text;
              -webkit-text-fill-color: transparent;
              will-change: opacity;
            "
          >
            FeatureMind
          </h1>
        </div>
      </div>

      <p
        v-motion="itemVariants"
        class="text-sm font-mono font-bold uppercase tracking-[0.2em] text-slate-500 mt-0 relative z-10"
      >
        Admin portal
      </p>
    </div>
  </div>
</template>

