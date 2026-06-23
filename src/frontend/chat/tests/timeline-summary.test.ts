import assert from 'node:assert/strict'
import test from 'node:test'
import { summarizeThought, truncateFilename } from '../app/lib/timeline.ts'

test('empty / nullish -> empty summary, no detail', () => {
  for (const value of [undefined, null, '', '   ']) {
    const r = summarizeThought(value as string | null | undefined)
    assert.equal(r.summary, '')
    assert.equal(r.detail, null)
  }
})

test('short plain text -> summary only, no disclosure', () => {
  const r = summarizeThought('Đang lập kế hoạch tra cứu chính sách nghỉ phép')
  assert.equal(r.detail, null)
  assert.match(r.summary, /chính sách/)
})

test('long plain text -> truncated summary + full detail behind disclosure', () => {
  const long = 'từ '.repeat(120).trim()
  const r = summarizeThought(long)
  assert.ok(r.summary.endsWith('…'))
  assert.ok(r.summary.length <= 142)
  assert.equal(r.detail, long)
})

test('JSON object -> human summary from a meaningful key, pretty JSON detail, never [object Object]', () => {
  const raw = JSON.stringify({ route: 'rag', reason: 'câu hỏi về chính sách nghỉ phép' })
  const r = summarizeThought(raw)
  assert.doesNotMatch(r.summary, /\[object Object\]|undefined|null/)
  assert.match(r.summary, /chính sách/)
  assert.ok(r.detail && r.detail.includes('\n'))
})

test('JSON with only nested objects -> neutral label, no leaked junk', () => {
  const raw = JSON.stringify({ meta: { a: 1 }, ctx: { b: 2 } })
  const r = summarizeThought(raw)
  assert.doesNotMatch(r.summary, /\[object Object\]|undefined|null/)
  assert.ok(r.summary.length > 0)
  assert.ok(r.detail && r.detail.includes('"meta"'))
})

test('truncateFilename keeps extension and adds ellipsis', () => {
  const t = truncateFilename('CNHC_Employee_Handbook_2024_final.pdf', 20)
  assert.ok(t.length <= 21)
  assert.ok(t.endsWith('.pdf'))
  assert.ok(t.includes('…'))
  // short names untouched
  assert.equal(truncateFilename('A.pdf', 20), 'A.pdf')
})
