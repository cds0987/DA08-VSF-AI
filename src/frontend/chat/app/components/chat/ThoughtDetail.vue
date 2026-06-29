<script setup lang="ts">
// Hiển thị 1 "thought" trong timeline kiểu DeepSeek: TÓM TẮT gọn + các SECTION CÓ NHÃN (cấu
// trúc: Tuyến xử lý / Lý do / Gợi ý…) hiện INLINE ngay (đọc được liền, không phải bấm) +
// disclosure "Xem suy luận gốc" cho prose CoT dài (không nhãn). Dùng chung MessageSteps & Pipeline.
import { ref, computed } from 'vue'
import { ChevronRight } from '@lucide/vue'
import type { ThoughtSummary } from '~/lib/timeline'

const props = defineProps<{ view: ThoughtSummary }>()

const open = ref(false)
// Section CÓ NHÃN = cấu trúc ngắn gọn -> hiện INLINE. Bỏ section trùng HỆT summary (tránh lặp).
const inlineSections = computed(() =>
  props.view.detail.filter(s => s.label && !(s.lines.length === 1 && s.lines[0] === props.view.summary)),
)
// Section KHÔNG nhãn = prose CoT/suy luận thô dài -> giấu sau disclosure (không lấn nội dung chính).
const rawSections = computed(() => props.view.detail.filter(s => !s.label))
</script>

<template>
  <div>
    <p v-if="view.summary" class="text-sm font-medium leading-relaxed text-slate-600 dark:text-muted-foreground">
      {{ view.summary }}
    </p>

    <!-- Cấu trúc CÓ NHÃN: hiện INLINE ngay (DeepSeek-style), thụt lề dưới đường kẻ trái mảnh -->
    <div
      v-if="inlineSections.length"
      class="mt-1.5 max-w-[68ch] border-l border-slate-200 pl-3 dark:border-white/10"
    >
      <div v-for="(sec, si) in inlineSections" :key="si" :class="si > 0 && 'mt-2'">
        <p class="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-muted-foreground">
          {{ sec.label }}
        </p>
        <p
          v-for="(line, li) in sec.lines"
          :key="li"
          class="mt-0.5 whitespace-pre-wrap break-words text-sm font-normal leading-relaxed text-slate-500 dark:text-muted-foreground"
        >
          {{ line }}
        </p>
      </div>
    </div>

    <!-- Suy luận gốc (prose CoT dài, không nhãn): giấu sau disclosure -> không lấn nội dung chính -->
    <template v-if="rawSections.length">
      <button
        type="button"
        class="-mx-1 mt-1 inline-flex items-center gap-1 rounded px-1 py-1.5 text-[13px] font-medium text-slate-500 transition-colors hover:text-slate-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 dark:text-muted-foreground dark:hover:text-foreground"
        :aria-expanded="open"
        @click="open = !open"
      >
        <ChevronRight class="td-chevron h-3 w-3 transition-transform" :class="open && 'rotate-90'" aria-hidden="true" />
        {{ open ? 'Ẩn suy luận gốc' : 'Xem suy luận gốc' }}
      </button>

      <div class="td-expand" :class="open && 'td-expand--open'" :aria-hidden="!open">
        <div class="td-expand__clip">
          <div
            class="custom-scrollbar mt-1 max-h-[220px] max-w-[68ch] overflow-auto border-l border-slate-200 pl-3 dark:border-white/10"
          >
            <p
              v-for="(line, li) in rawSections.flatMap(s => s.lines)"
              :key="li"
              class="whitespace-pre-wrap break-words text-sm font-normal leading-relaxed text-slate-500 dark:text-muted-foreground"
            >
              {{ line }}
            </p>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* Scrollbar khối "Chi tiết" / "Dữ liệu thô": dùng lại .custom-scrollbar global (light + dark)
   thay vì style td-scroll riêng (chỉ webkit + dark, không ăn -> trắng lạc lõng ở dark mode). */

.td-expand {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 240ms ease-out;
}
.td-expand--open { grid-template-rows: 1fr; }
.td-expand__clip { overflow: hidden; min-height: 0; }

/* Tôn trọng prefers-reduced-motion: chevron + expand không animate khi user yêu cầu giảm chuyển động. */
@media (prefers-reduced-motion: reduce) {
  .td-chevron { transition: none; }
  .td-expand { transition: none; }
}
</style>
