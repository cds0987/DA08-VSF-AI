<script setup lang="ts">
// Hiển thị 1 "thought" trong timeline kiểu DeepSeek: TÓM TẮT 1 dòng + disclosure "Xem chi
// tiết" (mức 1, human-readable có nhãn) + disclosure lồng "Xem dữ liệu thô" (mức 2, JSON thô).
// Mặc định đóng cả 2 cấp, gọn (max-height + overflow). Dùng chung cho MessageSteps & Pipeline.
import { ref } from 'vue'
import { ChevronRight } from '@lucide/vue'
import type { ThoughtSummary } from '~/lib/timeline'

const props = defineProps<{ view: ThoughtSummary }>()

const open = ref(false)
// Đơn sắc kiểu DeepSeek: chỉ phơi phần human-readable (detail), KHÔNG hiện JSON thô.
const hasDetail = () => props.view.detail.length > 0
</script>

<template>
  <div>
    <p v-if="view.summary" class="text-sm font-medium leading-relaxed text-slate-600 dark:text-muted-foreground">
      {{ view.summary }}
    </p>

    <template v-if="hasDetail()">
      <button
        type="button"
        class="mt-1 inline-flex items-center gap-1 rounded px-1 text-[13px] font-medium text-slate-400 transition-colors hover:text-slate-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 dark:text-muted-foreground/70 dark:hover:text-foreground"
        :aria-expanded="open"
        @click="open = !open"
      >
        <ChevronRight class="td-chevron h-3 w-3 transition-transform" :class="open && 'rotate-90'" aria-hidden="true" />
        {{ open ? 'Ẩn chi tiết' : 'Xem chi tiết' }}
      </button>

      <!-- Mở ra: chữ xám thụt lề dưới đường kẻ trái mảnh (DeepSeek-style) — KHÔNG box viền/nền màu -->
      <div
        v-show="open"
        class="custom-scrollbar mt-1 max-h-[220px] overflow-auto border-l border-slate-200 pl-3 dark:border-white/10"
      >
        <!-- Section human-readable có nhãn (không ngoặc/nháy JSON) -->
        <div
          v-for="(sec, si) in view.detail"
          :key="si"
          :class="si > 0 && 'mt-2'"
        >
          <p
            v-if="sec.label"
            class="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-muted-foreground/70"
          >
            {{ sec.label }}
          </p>
          <p
            v-for="(line, li) in sec.lines"
            :key="li"
            class="whitespace-pre-wrap break-words text-sm font-medium leading-relaxed text-slate-500 dark:text-muted-foreground"
            :class="sec.label && 'mt-0.5'"
          >
            {{ line }}
          </p>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* Scrollbar khối "Chi tiết" / "Dữ liệu thô": dùng lại .custom-scrollbar global (light + dark)
   thay vì style td-scroll riêng (chỉ webkit + dark, không ăn -> trắng lạc lõng ở dark mode). */

/* Tôn trọng prefers-reduced-motion: chevron không animate khi user yêu cầu giảm chuyển động. */
@media (prefers-reduced-motion: reduce) {
  .td-chevron {
    transition: none;
  }
}
</style>
