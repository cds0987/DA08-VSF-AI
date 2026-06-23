// Helper hiển thị TIMELINE agent kiểu DeepSeek: biến "thought" thô (text dài hoặc JSON/
// object stringify) thành:
//   - summary: 1 dòng người đọc được;
//   - detail: các SECTION human-readable có nhãn (Tuyến xử lý / Lý do / Các bước…),
//     KHÔNG còn ngoặc/nháy JSON ở mức 1;
//   - raw: JSON đẹp (tuỳ chọn) cho disclosure cấp 2 "Xem dữ liệu thô".
// KHÔNG bao giờ trả undefined/null/[object Object].

/** 1 mục chi tiết người đọc được: nhãn (có thể '') + 1..n dòng. */
export interface ThoughtDetailSection {
  label: string
  lines: string[]
}

export interface ThoughtSummary {
  /** Tóm tắt ngắn 1 dòng (có thể '' nếu thought rỗng -> caller bỏ qua). */
  summary: string
  /** Chi tiết người đọc được (mức 1). [] nếu không có gì để xem. */
  detail: ThoughtDetailSection[]
  /** JSON thô cho disclosure cấp 2 "Xem dữ liệu thô"; null nếu nguồn không phải JSON. */
  raw: string | null
}

const SUMMARY_MAX = 140

// Khóa "có nghĩa" ưu tiên khi thought là JSON object -> lấy làm TÓM TẮT người đọc được.
const PREFERRED_KEYS = [
  'summary', 'conclusion', 'reason', 'reasoning', 'decision',
  'route', 'intent', 'answer', 'message', 'text', 'note', 'status',
]

// Nhãn tiếng Việt cho field JSON khi dựng detail mức 1.
const FIELD_LABELS: Record<string, string> = {
  route: 'Tuyến xử lý',
  intent: 'Ý định',
  reason: 'Lý do',
  reasoning: 'Lý do',
  decision: 'Quyết định',
  action: 'Hành động',
  tool: 'Hành động',
  steps: 'Các bước',
  result: 'Kết quả',
  conclusion: 'Kết luận',
  summary: 'Tóm tắt',
  answer: 'Trả lời',
  message: 'Nội dung',
  note: 'Ghi chú',
  status: 'Trạng thái',
}

// Thứ tự field hiển thị (đọc theo logic: tuyến -> lý do -> các bước -> kết quả…).
const FIELD_ORDER = [
  'route', 'intent', 'reason', 'reasoning', 'decision', 'action', 'tool',
  'steps', 'result', 'conclusion', 'summary', 'answer', 'message', 'note', 'status',
]

// Nhãn role cho phần tử trong "steps" (đồng bộ với ROLE_LABEL ở MessageSteps/Pipeline).
const ROLE_LABEL: Record<string, string> = {
  rag_retrieve: 'Tìm tài liệu',
  hr_lookup: 'Tra cứu HR',
  synthesize_recommend: 'Tổng hợp & khuyến nghị',
  analyze: 'Phân tích',
  critic: 'Kiểm chứng',
  answer: 'Soạn câu trả lời',
}

function clampLine(value: string, max = SUMMARY_MAX): string {
  const one = value.replace(/\s+/g, ' ').trim()
  if (one.length <= max) return one
  const cut = one.slice(0, max)
  const space = cut.lastIndexOf(' ')
  return (space > max * 0.6 ? cut.slice(0, space) : cut).trimEnd() + '…'
}

// Chuyển 1 value JSON thành text an toàn. Object lồng nhau -> '' (TRÁNH "[object Object]");
// null/undefined -> ''. Mảng -> nối primitive bằng ', '.
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

// 1 phần tử "steps" -> "N. <nhãn role> — <hướng>". String -> "N. <string>".
function formatStep(step: unknown, i: number): string {
  const n = i + 1
  if (typeof step === 'string') return step.trim() ? `${n}. ${step.trim()}` : ''
  if (step && typeof step === 'object') {
    const s = step as Record<string, unknown>
    const role = typeof s.role === 'string' ? s.role : ''
    const dir = stringifyValue(s.direction ?? s.text ?? s.intent ?? s.label)
    const label = ROLE_LABEL[role] ?? role
    if (label && dir) return `${n}. ${label} — ${dir}`
    if (label) return `${n}. ${label}`
    if (dir) return `${n}. ${dir}`
  }
  return ''
}

// Dựng section detail mức 1 từ object. KHÔNG render object lồng nhau (để ở raw) -> không ngoặc/nháy.
function buildSections(obj: Record<string, unknown>): ThoughtDetailSection[] {
  const sections: ThoughtDetailSection[] = []
  const used = new Set<string>()

  const pushField = (key: string) => {
    used.add(key)
    if (key === 'steps') {
      const arr = obj.steps
      if (Array.isArray(arr)) {
        const lines = arr.map(formatStep).filter(Boolean)
        if (lines.length) sections.push({ label: FIELD_LABELS.steps, lines })
      }
      return
    }
    const text = stringifyValue(obj[key])
    if (text) sections.push({ label: FIELD_LABELS[key] ?? key, lines: [text] })
  }

  for (const key of FIELD_ORDER) {
    if (key in obj) pushField(key)
  }
  // Field lạ còn lại (primitive) — vẫn hiện để không giấu dữ liệu.
  for (const key of Object.keys(obj)) {
    if (used.has(key)) continue
    const text = stringifyValue(obj[key])
    if (text) sections.push({ label: FIELD_LABELS[key] ?? key, lines: [text] })
  }
  return sections
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
 *  - JSON/object: summary = khóa có nghĩa; detail = section có nhãn (human-readable);
 *    raw = JSON đẹp (cấp 2 "Xem dữ liệu thô").
 *  - JSON array: summary = nối phần tử; detail = "Các bước"; raw = JSON đẹp.
 *  - Text dài: summary cắt 1 dòng; detail = 1 section không nhãn chứa full text; raw = null.
 *  - Text ngắn: chỉ summary, không detail/raw.
 */
export function summarizeThought(raw?: string | null): ThoughtSummary {
  const text = (raw ?? '').trim()
  if (!text) return { summary: '', detail: [], raw: null }

  const parsed = tryParseJson(text)
  if (parsed && typeof parsed === 'object') {
    if (Array.isArray(parsed)) {
      const lines = parsed.map(formatStep).filter(Boolean)
      const human = clampLine(parsed.map(stringifyValue).filter(Boolean).join(', '))
      return {
        summary: human || 'Chi tiết suy luận',
        detail: lines.length ? [{ label: FIELD_LABELS.steps, lines }] : [],
        raw: JSON.stringify(parsed, null, 2),
      }
    }
    const obj = parsed as Record<string, unknown>
    const human = humanizeObject(obj)
    return {
      // Object toàn nested -> human rỗng -> nhãn trung tính, TUYỆT ĐỐI không [object Object].
      summary: human ? clampLine(human) : 'Chi tiết suy luận',
      detail: buildSections(obj),
      raw: JSON.stringify(parsed, null, 2),
    }
  }

  const oneLine = text.replace(/\s+/g, ' ').trim()
  if (oneLine.length <= SUMMARY_MAX) return { summary: oneLine, detail: [], raw: null }
  return { summary: clampLine(oneLine), detail: [{ label: '', lines: [text] }], raw: null }
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
