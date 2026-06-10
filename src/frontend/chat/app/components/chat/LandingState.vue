<script setup lang="ts">
import { Calendar, Clock, DollarSign, Umbrella } from '@lucide/vue'
import OctopusLogo from '~/components/OctopusLogo.vue'
import { useChatStore } from '~/stores/chat'

const chat = useChatStore()

const suggestions = [
  { text: 'Tôi còn bao nhiêu ngày nghỉ phép?', icon: Umbrella },
  { text: 'Tôi muốn xin nghỉ phép ngày mai.', icon: Calendar },
  { text: 'Kiểm tra lịch sử chấm công tháng này.', icon: Clock },
  { text: 'Xem phiếu lương gần nhất của tôi.', icon: DollarSign },
]
</script>

<template>
  <div
    class="flex flex-col items-center justify-center text-center pt-8"
    style="contain: content"
  >
    <div class="mb-6 relative group">
      <!-- (Logo part remains the same) -->
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
      <p class="text-lg font-medium text-slate-500">
        VSF’s Internal AI Assistant
      </p>
    </div>
    <p class="mt-6 text-base text-slate-400">How can I help you today?</p>

    <div class="mt-10 grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-xl">
      <button
        v-for="s in suggestions"
        :key="s.text"
        class="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-3.5 text-left text-[13px] font-medium text-slate-600 transition hover:border-blue-300 hover:bg-blue-50/50 hover:text-blue-600"
        @click="chat.ask(s.text, [])"
      >
        <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-50 text-slate-400 group-hover:bg-blue-100 group-hover:text-blue-500">
          <component :is="s.icon" class="h-4 w-4" />
        </div>
        {{ s.text }}
      </button>
    </div>
  </div>
</template>
