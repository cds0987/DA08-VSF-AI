import { onMounted, onUnmounted, ref } from 'vue'
import { shouldShowAskButton } from '~/lib/quote'

export function useAnswerSelection() {
  const visible = ref(false)
  const rect = ref<DOMRect | null>(null)
  const selectedText = ref('')
  const messageId = ref<string | null>(null)
  // Đang giữ chuột kéo chọn. Trong lúc kéo, selectionchange bắn liên tục -> KHÔNG hiện nút;
  // chỉ hiện sau khi buông chuột (mouseup).
  let isPointerDown = false

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
        isSelecting: isPointerDown,
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

  // Bắt đầu kéo chọn: ẩn nút cũ (nếu có) và đánh dấu đang giữ chuột.
  // Bỏ qua khi bấm vào CHÍNH nút "Hỏi FeatureMind" -> để click vào nút không tự ẩn nút.
  function onPointerDown(e: MouseEvent) {
    const target = e.target as Element | null
    if (target?.closest('.selection-ask-btn')) return
    isPointerDown = true
    hide()
  }

  // Buông chuột: hết kéo -> giờ mới đánh giá để hiện nút.
  function onPointerUp() {
    isPointerDown = false
    evaluate()
  }

  onMounted(() => {
    document.addEventListener('selectionchange', evaluate)
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('mouseup', onPointerUp)
    window.addEventListener('scroll', hide, true)
    window.addEventListener('resize', hide)
    document.addEventListener('keydown', onKeydown)
  })
  onUnmounted(() => {
    document.removeEventListener('selectionchange', evaluate)
    document.removeEventListener('mousedown', onPointerDown)
    document.removeEventListener('mouseup', onPointerUp)
    window.removeEventListener('scroll', hide, true)
    window.removeEventListener('resize', hide)
    document.removeEventListener('keydown', onKeydown)
  })

  return { visible, rect, selectedText, messageId, hide }
}
