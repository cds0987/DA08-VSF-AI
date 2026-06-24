import { onMounted, onUnmounted, ref } from 'vue'
import { shouldShowAskButton } from '~/lib/quote'

export function useAnswerSelection() {
  const visible = ref(false)
  const rect = ref<DOMRect | null>(null)
  const selectedText = ref('')
  const messageId = ref<string | null>(null)

  function hide() {
    visible.value = false
    rect.value = null
    selectedText.value = ''
    messageId.value = null
  }

  function evaluate() {
    try {
      const sel = window.getSelection()
      if (!sel || sel.rangeCount === 0) return hide()
      const range = sel.getRangeAt(0)
      const node = range.commonAncestorContainer
      const el = node.nodeType === Node.ELEMENT_NODE
        ? (node as Element)
        : node.parentElement
      const answerEl = el?.closest('[data-bot-answer]') ?? null
      const editableEl = el?.closest('input, textarea, [contenteditable="true"]') ?? null
      const r = range.getBoundingClientRect()
      const ok = shouldShowAskButton({
        text: sel.toString(),
        collapsed: sel.isCollapsed,
        inBotAnswer: !!answerEl,
        inEditable: !!editableEl,
        hasRect: !!r && r.width > 0 && r.height > 0,
      })
      if (!ok) return hide()
      selectedText.value = sel.toString().trim()
      messageId.value = answerEl!.getAttribute('data-message-id')
      rect.value = r
      visible.value = true
    } catch {
      hide()
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') hide()
  }

  onMounted(() => {
    document.addEventListener('selectionchange', evaluate)
    document.addEventListener('mouseup', evaluate)
    window.addEventListener('scroll', hide, true)
    window.addEventListener('resize', hide)
    document.addEventListener('keydown', onKeydown)
  })
  onUnmounted(() => {
    document.removeEventListener('selectionchange', evaluate)
    document.removeEventListener('mouseup', evaluate)
    window.removeEventListener('scroll', hide, true)
    window.removeEventListener('resize', hide)
    document.removeEventListener('keydown', onKeydown)
  })

  return { visible, rect, selectedText, messageId, hide }
}
