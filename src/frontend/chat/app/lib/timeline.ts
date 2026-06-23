// Helper hiển thị TIMELINE agent kiểu DeepSeek: biến "thought" thô (text dài hoặc JSON/
// object stringify) thành 1 dòng tóm tắt người đọc được + phần chi tiết thô để ẩn sau
// disclosure "Xem chi tiết". KHÔNG bao giờ trả undefined/null/[object Object].

export interface ThoughtSummary {
  /** Tóm tắt ngắn 1 dòng (có thể '' nếu thought rỗng -> caller bỏ qua). */
  summary: string
  /** Nội dung đầy đủ/thô cho disclosure; null khi không có gì thêm để xem. */
  detail: string | null
}

const SUMMARY_MAX = 140

// Khóa "có nghĩa" ưu tiên khi thought là JSON object -> lấy làm tóm tắt người đọc được
// thay vì in cả JSON. Thứ tự = độ ưu tiên.
const PREFERRED_KEYS = [
  'summary', 'conclusion', 'reason', 'reasoning', 'decision',
  'route', 'intent', 'answer', 'message', 'text', 'note', 'status',
]

function clampLine(value: string, max = SUMMARY_MAX): string {
  const one = value.replace(/\s+/g, ' ').trim()
  if (one.length <= max) return one
  const cut = one.slice(0, max)
  const space = cut.lastIndexOf(' ')
  return (space > max * 0.6 ? cut.slice(0, space) : cut).trimEnd() + '…'
}

// Chuyển 1 value JSON thành text an toàn cho tóm tắt. Object/lồng nhau -> '' (để dành cho
// detail) nhằm TRÁNH "[object Object]". null/undefined -> ''.
function stringifyValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(stringifyValue).filter(Boolean).join(', ')
  return ''
}

function humanizeObject(obj: Record<string, unknown>): string {
  for (const key of PREFERRED_KEYS) {
    const text = stringifyValue(obj[key])
    if (text) return text
  }
  // Fallback: ghép cặp key: value primitive (bỏ object lồng nhau -> không [object Object]).
  const pairs: string[] = []
  for (const [key, value] of Object.entries(obj)) {
    const text = stringifyValue(value)
    if (text) pairs.push(`${key}: ${text}`)
  }
  return pairs.join(' · ')
}

function tryParseJson(text: string): unknown {
  if (!/^[[{]/.test(text)) return undefined
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

/**
 * Tóm tắt 1 thought cho timeline.
 *  - JSON/object: lấy khóa có nghĩa làm summary, JSON đẹp làm detail (ẩn mặc định).
 *  - Text dài: cắt summary 1 dòng, giữ full trong detail.
 *  - Text ngắn: hiện hết, không cần detail.
 */
export function summarizeThought(raw?: string | null): ThoughtSummary {
  const text = (raw ?? '').trim()
  if (!text) return { summary: '', detail: null }

  const parsed = tryParseJson(text)
  if (parsed && typeof parsed === 'object') {
    const human = humanizeObject(parsed as Record<string, unknown>)
    return {
      // Object toàn nested -> human rỗng -> nhãn trung tính, TUYỆT ĐỐI không [object Object].
      summary: human ? clampLine(human) : 'Chi tiết suy luận',
      detail: JSON.stringify(parsed, null, 2),
    }
  }

  const oneLine = text.replace(/\s+/g, ' ').trim()
  if (oneLine.length <= SUMMARY_MAX) return { summary: oneLine, detail: null }
  return { summary: clampLine(oneLine), detail: text }
}

/** Cắt tên tệp dài, GIỮ đuôi (vd "CNHC_Employee_Handbook_2024.pdf" -> "CNHC_Employee…pdf"). */
export function truncateFilename(name?: string | null, max = 24): string {
  const value = (name ?? '').trim()
  if (value.length <= max) return value
  const dot = value.lastIndexOf('.')
  if (dot > 0 && value.length - dot <= 6) {
    const ext = value.slice(dot)
    const head = value.slice(0, Math.max(1, max - ext.length - 1))
    return `${head}…${ext}`
  }
  return value.slice(0, Math.max(1, max - 1)) + '…'
}
