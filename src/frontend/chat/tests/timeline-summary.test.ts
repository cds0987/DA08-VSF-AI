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

test('truncateFilename keeps extension and adds ellipsis', () => {
  const t = truncateFilename('CNHC_Employee_Handbook_2024_final.pdf', 20)
  assert.ok(t.length <= 21)
  assert.ok(t.endsWith('.pdf'))
  assert.ok(t.includes('…'))
  assert.equal(truncateFilename('A.pdf', 20), 'A.pdf')
})
