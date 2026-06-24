import { ref, type Ref } from 'vue'
import { useEventListener } from '@vueuse/core'

// Thuần & test được: còn cách đáy <= threshold px thì coi như đang ghim đáy.
export function isNearBottom(
  el: Pick<HTMLElement, 'scrollHeight' | 'scrollTop' | 'clientHeight'>,
  threshold = 96,
): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold
}

export function useChatAutoScroll(blocked: Ref<boolean>) {
  const scrollRef = ref<HTMLDivElement | null>(null)
  const isPinnedToBottom = ref(true)
  let autoRaf: number | null = null
  let instantRaf: number | null = null

  function scrollToBottom(behavior: ScrollBehavior) {
    const el = scrollRef.value
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior })
    isPinnedToBottom.value = true
  }

  // Cập nhật cờ ghim mỗi khi user cuộn -> quyết định có auto-scroll hay không.
  function onScroll() {
    const el = scrollRef.value
    if (el) isPinnedToBottom.value = isNearBottom(el)
  }

  // Stream/update: chỉ cuộn khi đang ghim đáy & không bị chặn. Gom 1 lần/frame.
  function scheduleAutoScroll() {
    if (!import.meta.client) return
    if (blocked.value || !isPinnedToBottom.value) return
    if (autoRaf !== null) return
    autoRaf = requestAnimationFrame(() => {
      autoRaf = null
      if (!blocked.value && isPinnedToBottom.value) scrollToBottom('auto')
    })
  }

  // Load lịch sử / đổi hội thoại / user gửi tin: BẮT BUỘC cuộn xuống + ghim lại (double rAF cho DOM kịp render).
  function scheduleInstantScroll() {
    if (!import.meta.client) return
    if (instantRaf !== null) cancelAnimationFrame(instantRaf)
    instantRaf = requestAnimationFrame(() => {
      instantRaf = requestAnimationFrame(() => {
        instantRaf = null
        scrollToBottom('auto')
      })
    })
  }

  useEventListener(scrollRef, 'scroll', onScroll, { passive: true })

  return { scrollRef, isPinnedToBottom, scheduleAutoScroll, scheduleInstantScroll }
}
