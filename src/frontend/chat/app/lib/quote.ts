export interface Quote {
  messageId: string
  text: string
}

export interface SelectionProbe {
  text: string
  collapsed: boolean
  inBotAnswer: boolean
  inEditable: boolean
  hasRect: boolean
  // Đang giữ chuột kéo chọn — chưa buông. Khi true thì KHÔNG hiện nút (chờ buông chuột).
  isSelecting: boolean
}

// Dựng nội dung gửi đi: mỗi dòng quote thành blockquote, rồi dòng trống + câu hỏi.
export function buildQuotedContent(quote: Quote | null, question: string): string {
  const q = question.trim()
  if (!quote || !quote.text.trim()) return q
  const blockquote = quote.text.trim().split('\n').map(line => `> ${line}`).join('\n')
  return `${blockquote}\n\n${q}`
}

// Cắt ngắn cho chip; full text vẫn nằm trong store.
export function truncateQuote(text: string, max = 140): string {
  const t = text.trim().replace(/\s+/g, ' ')
  return t.length > max ? `${t.slice(0, max).trimEnd()}…` : t
}

export function shouldShowAskButton(p: SelectionProbe): boolean {
  return Boolean(p.text.trim()) && !p.collapsed && p.inBotAnswer && !p.inEditable && p.hasRect && !p.isSelecting
}
