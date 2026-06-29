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

const SUMMARY_MAX = 240

// Khóa "có nghĩa" ưu tiên khi thought là JSON object -> lấy làm TÓM TẮT người đọc được.
// KHÔNG đưa 'route' vào: 'heavy'/'light' là jargon nội bộ, không phải tóm tắt người đọc được.
const PREFERRED_KEYS = [
  'summary', 'conclusion', 'reason', 'reasoning', 'decision',
  'intent', 'answer', 'message', 'text', 'note', 'status',
]

// Field ẨN khỏi phần hiển thị (vẫn còn trong `raw` cấp 2). Lý do: thought kế hoạch orchestrate
// chứa các field ĐÃ hiển thị ở chỗ khác hoặc không phù hợp panel suy nghĩ:
//   steps       -> đã vẽ thành lane plan-step ngay dưới header (phase:plan) -> in lại = trùng.
//   answer_hint -> bản NHÁP câu trả lời (light route stream chính nó làm câu trả lời) -> đúp.
//   route       -> 'heavy'/'light' jargon nội bộ.
const HIDDEN_KEYS = new Set(['steps', 'answer_hint', 'route'])

// Nhãn tiếng Việt cho field JSON khi dựng detail mức 1.
const FIELD_LABELS: Record<string, string> = {
  route: 'Tuyến xử lý',
  intent: 'Ý định',
  reason: 'Lý do',
  reasoning: 'Lý do',
  answer_hint: 'Gợi ý trả lời',
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
  'route', 'intent', 'reason', 'reasoning', 'answer_hint', 'decision', 'action', 'tool',
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
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : ''  // chặn NaN/Infinity
  if (typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(stringifyValue).filter(Boolean).join(', ')
  return ''
}

function humanizeObject(obj: Record<string, unknown>): string {
  for (const key of PREFERRED_KEYS) {
    const text = stringifyValue(obj[key])
    if (text) return text
  }
  // Fallback: ghép cặp key: value primitive (bỏ object lồng nhau -> không [object Object];
  // bỏ field ẩn -> không lộ jargon route/answer_hint vào tóm tắt).
  const pairs: string[] = []
  for (const [key, value] of Object.entries(obj)) {
    if (HIDDEN_KEYS.has(key)) continue
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
    const dir = stringifyValue(s.direction ?? s.input ?? s.text ?? s.intent ?? s.label)
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
  // Đánh dấu field ẩn là "đã dùng" -> bỏ qua ở CẢ vòng FIELD_ORDER lẫn vòng field lạ.
  const used = new Set<string>(HIDDEN_KEYS)

  const pushField = (key: string) => {
    if (HIDDEN_KEYS.has(key)) return   // ẩn khỏi hiển thị (vẫn còn ở raw)
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

// ── DEFENSIVE: BE có thể nhét raw JSON/debug LẪN trong text (sai format). Coi text là
//    nội dung KHÔNG tin cậy: dò + bóc khối JSON, KHÔNG để raw lộ ra first-level. ──

// Index '{' hoặc '[' đầu tiên kể từ `from`. -1 nếu không có.
function firstJsonStart(text: string, from: number): number {
  for (let i = from; i < text.length; i++) {
    const c = text[i]
    if (c === '{' || c === '[') return i
  }
  return -1
}

// Index dấu đóng khớp với mở tại `start`, TÔN TRỌNG chuỗi "" và ký tự thoát \". -1 nếu lệch.
function matchJsonEnd(text: string, start: number): number {
  let depth = 0
  let inStr = false
  let esc = false
  for (let i = start; i < text.length; i++) {
    const ch = text[i]
    if (inStr) {
      if (esc) esc = false
      else if (ch === '\\') esc = true
      else if (ch === '"') inStr = false
      continue
    }
    if (ch === '"') inStr = true
    else if (ch === '{' || ch === '[') depth++
    else if (ch === '}' || ch === ']') {
      depth--
      if (depth === 0) return i
    }
  }
  return -1
}

interface ExtractedJson { jsonText: string; parsed: unknown; before: string; after: string }

// Bóc KHỐI JSON top-level HỢP LỆ ĐẦU TIÊN trong text (chỉ JSON.parse, không eval). Quét lần lượt
// từng vị trí '{'/'[' -> khớp ngoặc -> thử parse; khối hỏng thì thử khối kế. null nếu không có.
export function extractFirstJsonObject(text: string): ExtractedJson | null {
  for (let start = firstJsonStart(text, 0); start >= 0; start = firstJsonStart(text, start + 1)) {
    const end = matchJsonEnd(text, start)
    if (end < 0) continue
    const jsonText = text.slice(start, end + 1)
    try {
      const parsed = JSON.parse(jsonText)
      if (parsed && typeof parsed === 'object') {
        return { jsonText, parsed, before: text.slice(0, start), after: text.slice(end + 1) }
      }
    } catch {
      // khối nhìn như JSON nhưng hỏng -> bỏ qua, thử khối kế
    }
  }
  return null
}

// Text "trông như JSON/debug" (để xử lý cả khi parse hỏng): có ngoặc kèm cặp "key":.
const JSON_LIKE_RE = /[{[][\s\S]*?["'][^"']*["']\s*:/
export function isDebugJsonLike(text: string): boolean {
  return JSON_LIKE_RE.test(text) || /["']?(route|reasoning|steps|depends_on|answer_hint)["']?\s*:/.test(text)
}

// Bỏ MỌI khối JSON khỏi text -> còn lại phần ngôn ngữ tự nhiên sạch. Khối hợp lệ: bóc hẳn.
// Khối nhìn-như-JSON nhưng hỏng (không khớp/không parse được): cắt từ vị trí mở -> KHÔNG dump payload.
function stripJsonLikeBlocks(text: string): string {
  let out = text
  let guard = 0
  let res = extractFirstJsonObject(out)
  while (res && guard++ < 50) {
    out = `${res.before} ${res.after}`
    res = extractFirstJsonObject(out)
  }
  const idx = firstJsonStart(out, 0)
  // Phần đuôi còn ngoặc + giống "key:" -> là JSON hỏng -> cắt bỏ (không để lộ/đổ thô).
  if (idx >= 0 && /["']?[\w$]+["']?\s*:/.test(out.slice(idx))) {
    out = out.slice(0, idx)
  }
  return out.replace(/\s+/g, ' ').trim()
}

// Cắt "recap kế hoạch" kỹ thuật ở đuôi prose orchestrator (vd "Plan: 1 step rag_retrieve
// input=… depends_on…") — vốn TRÙNG với danh sách plan step render ngay bên dưới timeline,
// nên thừa + lộ token kỹ thuật ra người dùng. CHỈ cắt khi có dấu hiệu kỹ thuật RÕ RÀNG; prose
// thường (không marker) giữ NGUYÊN. Cắt làm rỗng/cụt -> giữ nguyên (không mất nội dung).
const PLAN_RECAP_RE = /\b(?:plan|kế hoạch)\s*[:：]\s*\d|\bdepends_on\b|\bstep_id\b|\binput\s*=|\breasoning\s*=/i
function stripPlanRecap(text: string): string {
  const m = PLAN_RECAP_RE.exec(text)
  if (!m) return text
  const head = text.slice(0, m.index).replace(/[\s.;,:—–-]+$/, '').trim()
  return head.length >= 20 ? head : text
}

// Dọn phần ngôn ngữ tự nhiên quanh khối JSON: bỏ khối JSON + nhiễu nhãn "Output JSON" + recap kỹ thuật.
function cleanNaturalLanguage(text: string): string {
  return stripPlanRecap(stripJsonLikeBlocks(text).replace(/^output\s*json[.:]?\s*/i, '')).trim()
}

// Dựng kết quả từ 1 JSON đã parse (object/array) + phần NL hữu ích (nếu có).
function summarizeParsed(parsed: unknown, naturalLanguage: string): ThoughtSummary {
  const nl = cleanNaturalLanguage(naturalLanguage)
  let sections: ThoughtDetailSection[]
  let human: string
  if (Array.isArray(parsed)) {
    const lines = parsed.map(formatStep).filter(Boolean)
    sections = lines.length ? [{ label: FIELD_LABELS.steps, lines }] : []
    human = clampLine(parsed.map(stringifyValue).filter(Boolean).join(', '))
  } else {
    const obj = parsed as Record<string, unknown>
    sections = buildSections(obj)
    human = humanizeObject(obj)
  }
  // summary ưu tiên FIELD CÓ NGHĨA (sạch, tiếng Việt) hơn prose CoT thô — prose có thể là
  // chuỗi suy luận tiếng Anh dài dòng (reasoning_content) -> dòng tóm tắt gọn, đúng trọng tâm.
  // NL chỉ dùng làm tóm tắt khi object không có field nào đọc được.
  const summary = clampLine(human || nl) || 'Chi tiết suy luận'
  // Section CÓ NHÃN (cấu trúc) đứng TRƯỚC -> ThoughtDetail hiện INLINE ngay (không phải bấm).
  // Prose CoT dài (KHÔNG nhãn) xếp CUỐI -> nằm sau "Xem suy luận gốc", không lấn nội dung chính.
  const detail: ThoughtDetailSection[] = [...sections]
  if (nl && nl.length > SUMMARY_MAX) detail.push({ label: '', lines: [nl] })
  return { summary, detail, raw: JSON.stringify(parsed, null, 2) }
}

/**
 * Tóm tắt 1 thought cho timeline (PHÒNG THỦ với text BE không tin cậy).
 *  1. Có khối JSON HỢP LỆ (kể cả lẫn trong text): summary = NL/khóa có nghĩa; detail = section
 *     human-readable; raw = JSON đẹp (cấp 2). First-level KHÔNG có ngoặc/nháy JSON.
 *  2. Trông như JSON nhưng PARSE HỎNG: bóc/cắt khối -> chỉ giữ NL sạch; raw = null (không đổ thô).
 *  3. Text thường dài: summary cắt 1 dòng; detail = 1 section không nhãn; raw = null.
 *  4. Text ngắn: chỉ summary.
 */
export function summarizeThought(raw?: string | null): ThoughtSummary {
  const text = (raw ?? '').trim()
  if (!text) return { summary: '', detail: [], raw: null }

  // (1) JSON hợp lệ ở bất cứ đâu trong text -> render human-readable.
  const extracted = extractFirstJsonObject(text)
  if (extracted) {
    return summarizeParsed(extracted.parsed, `${extracted.before} ${extracted.after}`)
  }

  // (2) Trông như JSON/debug nhưng không parse được -> KHÔNG dump; bóc/cắt, giữ NL sạch.
  if (isDebugJsonLike(text)) {
    const cleaned = stripPlanRecap(stripJsonLikeBlocks(text))
    const summary = clampLine(cleaned) || 'Chi tiết suy luận'
    const detail = cleaned.length > SUMMARY_MAX ? [{ label: '', lines: [cleaned] }] : []
    return { summary, detail, raw: null }
  }

  // (3)(4) Text thường — bỏ "recap kế hoạch" kỹ thuật ở đuôi nếu có (trùng plan step bên dưới).
  const stripped = stripPlanRecap(text)
  const oneLine = stripped.replace(/\s+/g, ' ').trim()
  if (oneLine.length <= SUMMARY_MAX) return { summary: oneLine, detail: [], raw: null }
  return { summary: clampLine(oneLine), detail: [{ label: '', lines: [stripped] }], raw: null }
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
