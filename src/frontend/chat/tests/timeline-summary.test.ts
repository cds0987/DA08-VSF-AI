import assert from 'node:assert/strict'
import test from 'node:test'
import { summarizeThought, truncateFilename } from '../app/lib/timeline.ts'

// Gộp toàn bộ text của các section human-readable (KHÔNG gồm raw) — để khẳng định
// first-level detail không chứa dấu ngoặc/nháy JSON.
function detailText(detail: { label: string; lines: string[] }[]): string {
  return detail.map(s => `${s.label} ${s.lines.join(' ')}`).join(' ')
}

test('empty / nullish -> empty summary, no detail, no raw', () => {
  for (const value of [undefined, null, '', '   ']) {
    const r = summarizeThought(value as string | null | undefined)
    assert.equal(r.summary, '')
    assert.deepEqual(r.detail, [])
    assert.equal(r.raw, null)
  }
})

test('short plain text -> summary only, no disclosure', () => {
  const r = summarizeThought('Đang lập kế hoạch tra cứu chính sách nghỉ phép')
  assert.deepEqual(r.detail, [])
  assert.equal(r.raw, null)
  assert.match(r.summary, /chính sách/)
})

test('long plain text -> truncated summary + full text as a label-less detail section, no raw', () => {
  const long = 'từ '.repeat(120).trim()
  const r = summarizeThought(long)
  assert.ok(r.summary.endsWith('…'))
  assert.ok(r.summary.length <= 142)
  assert.equal(r.detail.length, 1)
  assert.equal(r.detail[0].label, '')
  assert.equal(r.detail[0].lines[0], long)
  assert.equal(r.raw, null)
})

test('JSON object -> human-readable labeled detail (no braces/quotes), raw JSON only second-level', () => {
  const raw = JSON.stringify({ route: 'heavy', reason: 'câu hỏi về chính sách nghỉ phép' })
  const r = summarizeThought(raw)
  // summary sạch
  assert.doesNotMatch(r.summary, /\[object Object\]|undefined|null/)
  // first-level detail: có nhãn người đọc được, KHÔNG có ngoặc/nháy JSON
  const text = detailText(r.detail)
  assert.match(text, /Tuyến xử lý/)
  assert.match(text, /Lý do/)
  assert.match(text, /chính sách/)
  assert.doesNotMatch(text, /[{}"]/)
  // raw JSON nằm ở second-level (có ngoặc + xuống dòng)
  assert.ok(r.raw && r.raw.includes('\n') && r.raw.includes('"route"'))
})

test('JSON with steps array -> "Các bước" section, numbered + role label, no raw braces leaked', () => {
  const raw = JSON.stringify({
    route: 'heavy',
    steps: [
      { role: 'rag_retrieve', direction: 'tìm tài liệu liên quan' },
      { role: 'answer', direction: 'tổng hợp câu trả lời' },
    ],
  })
  const r = summarizeThought(raw)
  const steps = r.detail.find(s => s.label === 'Các bước')
  assert.ok(steps, 'phải có section Các bước')
  assert.equal(steps!.lines.length, 2)
  assert.match(steps!.lines[0], /^1\./)
  assert.match(steps!.lines[0], /Tìm tài liệu/)
  assert.doesNotMatch(detailText(r.detail), /[{}"]/)
})

test('JSON with only nested objects -> neutral summary, empty first-level detail, raw available', () => {
  const raw = JSON.stringify({ meta: { a: 1 }, ctx: { b: 2 } })
  const r = summarizeThought(raw)
  assert.doesNotMatch(r.summary, /\[object Object\]|undefined|null/)
  assert.ok(r.summary.length > 0)
  // không bịa nhãn từ object lồng nhau -> first-level rỗng, dữ liệu vẫn còn ở raw
  assert.deepEqual(r.detail, [])
  assert.ok(r.raw && r.raw.includes('"meta"'))
})

// ── DEFENSIVE: BE có thể nhét raw JSON LẪN trong text (sai format) — FE phải chặn lộ ──

// Không bao giờ để dấu hiệu JSON/debug rò ra first-level (summary + detail human-readable).
function assertNoJsonLeak(r: { summary: string; detail: { label: string; lines: string[] }[] }) {
  const surface = `${r.summary} ${detailText(r.detail)}`
  assert.doesNotMatch(surface, /[{}]/, 'không được lộ ngoặc nhọn JSON')
  assert.doesNotMatch(surface, /"\w+"\s*:/, 'không được lộ cặp "key": JSON')
  assert.doesNotMatch(surface, /\[object Object\]|undefined|null|NaN/)
}

test('embedded JSON after a natural-language prefix -> human-readable detail, raw second-level only', () => {
  const raw = 'Output JSON.Mình hiểu bạn muốn biết nếu đi sớm thì có được thưởng gì không. '
    + JSON.stringify({
      route: 'heavy',
      reasoning: 'Mình hiểu bạn hỏi về việc đi sớm có được thưởng hay không',
      steps: [
        { id: 1, role: 'rag_retrieve', direction: 'Trích các điều khoản về thưởng' },
        { id: 2, role: 'synthesize_recommend', direction: 'kết quả từ step trước' },
      ],
    })
  const r = summarizeThought(raw)
  assertNoJsonLeak(r)
  // prefix NL hữu ích vẫn còn (đã bỏ nhiễu "Output JSON.")
  assert.match(r.summary, /Mình hiểu/)
  assert.doesNotMatch(r.summary, /Output JSON/)
  // detail có nhãn người đọc được
  const text = detailText(r.detail)
  assert.match(text, /Lý do|Các bước/)
  // raw JSON đầy đủ chỉ ở cấp 2
  assert.ok(r.raw && r.raw.includes('"route"') && r.raw.includes('\n'))
})

test('embedded JSON with prefix + suffix -> extracts first object, no raw leak', () => {
  const raw = 'Some prefix {"route":"heavy","reasoning":"vì abc","steps":[]} some suffix'
  const r = summarizeThought(raw)
  assertNoJsonLeak(r)
  assert.ok(r.raw && r.raw.includes('"route"'))
})

test('pure embedded JSON object (no useful prefix) -> labeled detail, no braces in first level', () => {
  const raw = '{"route":"heavy","reasoning":"chính sách thưởng","steps":[{"role":"rag_retrieve","direction":"tìm tài liệu"}]}'
  const r = summarizeThought(raw)
  assertNoJsonLeak(r)
  assert.match(detailText(r.detail), /Tuyến xử lý|Lý do|Các bước/)
  assert.ok(r.raw && r.raw.includes('"steps"'))
})

test('malformed JSON-like payload -> stripped, never dumped, raw is null', () => {
  const raw = 'Trả lời: {"route":"heavy", "reasoning": oops not valid json, steps missing'
  const r = summarizeThought(raw)
  assertNoJsonLeak(r)
  // không dump payload thô -> không có raw, summary giữ phần NL sạch
  assert.equal(r.raw, null)
  assert.match(r.summary, /Trả lời/)
})

test('plain text that merely mentions the word json -> untouched, no false strip', () => {
  const r = summarizeThought('Mình sẽ trả về json cho bạn sau khi tra cứu xong')
  assert.match(r.summary, /json/)
  assert.deepEqual(r.detail, [])
  assert.equal(r.raw, null)
})

test('truncateFilename keeps extension and adds ellipsis', () => {
  const t = truncateFilename('CNHC_Employee_Handbook_2024_final.pdf', 20)
  assert.ok(t.length <= 21)
  assert.ok(t.endsWith('.pdf'))
  assert.ok(t.includes('…'))
  assert.equal(truncateFilename('A.pdf', 20), 'A.pdf')
})
