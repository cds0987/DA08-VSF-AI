<script setup lang="ts">
// Hiển thị 1 "thought" trong timeline kiểu DeepSeek: TÓM TẮT 1 dòng + disclosure "Xem chi
// tiết" (mức 1, human-readable có nhãn) + disclosure lồng "Xem dữ liệu thô" (mức 2, JSON thô).
// Mặc định đóng cả 2 cấp, gọn (max-height + overflow). Dùng chung cho MessageSteps & Pipeline.
import { ref } from 'vue'
import { ChevronRight } from '@lucide/vue'
import type { ThoughtSummary } from '~/lib/timeline'

const props = defineProps<{ view: ThoughtSummary }>()

const open = ref(false)
const rawOpen = ref(false)
const hasDetail = () => props.view.detail.length > 0 || !!props.view.raw
</script>

<template>
  <div>
    <p v-if="view.summary" class="text-[13.5px] leading-relaxed text-slate-600 dark:text-muted-foreground">
      {{ view.summary }}
    </p>

    <template v-if="hasDetail()">
      <button
        type="button"
        class="mt-1 inline-flex items-center gap-1 rounded px-1 text-[12px] font-medium text-slate-400 transition-colors hover:text-slate-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 dark:text-muted-foreground/70 dark:hover:text-foreground"
        :aria-expanded="open"
        @click="open = !open"
      >
        <ChevronRight class="td-chevron h-3 w-3 transition-transform" :class="open && 'rotate-90'" aria-hidden="true" />
        {{ open ? 'Ẩn chi tiết' : 'Xem chi tiết' }}
      </button>

      <div
        v-show="open"
        class="td-scroll mt-1 max-h-[200px] overflow-auto rounded-md border border-slate-200/60 bg-slate-50/60 px-2.5 py-2 dark:border-white/10 dark:bg-white/[0.03]"
      >
        <!-- Mức 1: section human-readable có nhãn (không ngoặc/nháy JSON) -->
        <div
          v-for="(sec, si) in view.detail"
          :key="si"
          :class="si > 0 && 'mt-2'"
        >
          <p
            v-if="sec.label"
            class="text-[10.5px] font-semibold uppercase tracking-wide text-slate-400 dark:text-muted-foreground/70"
          >
            {{ sec.label }}
          </p>
          <p
            v-for="(line, li) in sec.lines"
            :key="li"
            class="whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-slate-600 dark:text-muted-foreground"
            :class="sec.label && 'mt-0.5'"
          >
            {{ line }}
          </p>
        </div>

        <!-- Mức 2: JSON thô (tuỳ chọn) — disclosure lồng, mặc định đóng -->
        <template v-if="view.raw">
          <button
            type="button"
            class="mt-2 inline-flex items-center gap-1 rounded px-1 text-[11px] font-medium text-slate-400 transition-colors hover:text-slate-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 dark:text-muted-foreground/60 dark:hover:text-foreground"
            :aria-expanded="rawOpen"
            @click="rawOpen = !rawOpen"
          >
            <ChevronRight class="td-chevron h-3 w-3 transition-transform" :class="rawOpen && 'rotate-90'" aria-hidden="true" />
            {{ rawOpen ? 'Ẩn dữ liệu thô' : 'Xem dữ liệu thô' }}
          </button>
          <pre
            v-show="rawOpen"
            class="td-scroll mt-1 max-h-[160px] overflow-auto whitespace-pre-wrap break-words rounded border border-slate-200/60 bg-white/60 px-2 py-1.5 text-[11.5px] leading-relaxed text-slate-500 dark:border-white/10 dark:bg-black/20 dark:text-muted-foreground/80"
          >{{ view.raw }}</pre>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* Dark mode scrollbar: hoà vào nền tối, không bị trắng lạc lõng. */
:global(.dark) .td-scroll {
  scrollbar-color: rgba(255, 255, 255, 0.15) transparent;
  scrollbar-width: thin;
}
:global(.dark) .td-scroll::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
:global(.dark) .td-scroll::-webkit-scrollbar-track {
  background: transparent;
}
:global(.dark) .td-scroll::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.15);
  border-radius: 9999px;
}
:global(.dark) .td-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.25);
}

/* Tôn trọng prefers-reduced-motion: chevron không animate khi user yêu cầu giảm chuyển động. */
@media (prefers-reduced-motion: reduce) {
  .td-chevron {
    transition: none;
  }
}
</style>
