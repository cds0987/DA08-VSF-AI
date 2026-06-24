import assert from 'node:assert/strict'
import test from 'node:test'
import { findLastBlockBoundary, createStreamingRenderer } from '../app/lib/streamingMarkdown.ts'

test('boundary cơ bản: sau "\\n\\n" cuối cùng', () => {
  assert.equal(findLastBlockBoundary('a\n\nb'), 3)        // "a\n\n" | "b"
  assert.equal(findLastBlockBoundary('a\n\nb\n\nc'), 6)   // "a\n\nb\n\n" | "c"
})

test('không có blank line -> 0', () => {
  assert.equal(findLastBlockBoundary('hello world'), 0)
  assert.equal(findLastBlockBoundary('một dòng\nvẫn một block'), 0)
})

test('1 dấu newline cuối (không phải dòng trống) KHÔNG tính là ranh giới', () => {
  assert.equal(findLastBlockBoundary('ab\n'), 0)
  assert.equal(findLastBlockBoundary('a\n\n'), 3)   // có dòng trống thật -> tail rỗng
})

test('"\\n\\n" bên trong fenced code đã đóng KHÔNG tính', () => {
  // Toàn bộ là 1 code block đã đóng, không có blank line ngoài fence -> 0
  assert.equal(findLastBlockBoundary('```\ncode\n\nmore\n```'), 0)
})

test('chỉ lấy blank line NGOÀI fence', () => {
  const src = '```\ncode\n\nx\n```\n\ntext'
  // ranh giới hợp lệ là "\n\n" sau khi fence đã đóng -> trước "text"
  assert.equal(src.slice(findLastBlockBoundary(src)), 'text')
})

test('fence mở chưa đóng -> mọi "\\n\\n" bên trong bị bỏ -> 0', () => {
  assert.equal(findLastBlockBoundary('```\ncode\n\nmore'), 0)
})

// Fake deps: bọc rõ ràng để assert nội dung + đếm số lần gọi.
function fakeDeps() {
  const calls: string[] = []
  return {
    calls,
    render: (s: string) => { calls.push(s); return `<R>${s}</R>` },
    sanitize: (h: string) => `[${h}]`,
  }
}

test('toHtml: ghép prefix đã cache + tail render mỗi lần', () => {
  const d = fakeDeps()
  const r = createStreamingRenderer(d)
  // content = "a\n\nb" -> prefix "a\n\n", tail "b"
  const out = r.toHtml('a\n\nb')
  assert.equal(out, '[<R>a\n\n</R>][<R>b</R>]')
})

test('toHtml: prefix CHỈ render lại khi ranh giới tiến lên', () => {
  const d = fakeDeps()
  const r = createStreamingRenderer(d)
  r.toHtml('a\n\n')        // boundary=3, render prefix "a\n\n"
  d.calls.length = 0
  r.toHtml('a\n\nb')       // cùng boundary -> KHÔNG render lại prefix, chỉ tail "b"
  assert.deepEqual(d.calls, ['b'], 'chỉ render tail, không render lại prefix')
  d.calls.length = 0
  r.toHtml('a\n\nb\n\n')   // boundary tiến -> render lại prefix "a\n\nb\n\n"
  assert.deepEqual(d.calls, ['a\n\nb\n\n'], 'render prefix mới khi boundary tiến')
})

test('toHtml: tail rỗng -> chỉ prefix', () => {
  const d = fakeDeps()
  const r = createStreamingRenderer(d)
  assert.equal(r.toHtml('a\n\n'), '[<R>a\n\n</R>]')
})

test('toHtml: content không nối tiếp prefix -> reset cache', () => {
  const d = fakeDeps()
  const r = createStreamingRenderer(d)
  r.toHtml('a\n\nb')           // cache prefix "a\n\n"
  d.calls.length = 0
  const out = r.toHtml('x\n\ny') // không bắt đầu bằng "a\n\n" -> reset, render lại
  assert.equal(out, '[<R>x\n\n</R>][<R>y</R>]')
})

test('reset(): xoá cache, prefix render lại lần sau', () => {
  const d = fakeDeps()
  const r = createStreamingRenderer(d)
  r.toHtml('a\n\nb')
  r.reset()
  d.calls.length = 0
  r.toHtml('a\n\nb')
  assert.ok(d.calls.includes('a\n\n'), 'sau reset phải render lại prefix')
})

import { readFile } from 'node:fs/promises'
const root = new URL('../', import.meta.url)
const read = (p: string) => readFile(new URL(p, root), 'utf8')

test('AnswerBlock: nhánh streaming dùng createStreamingRenderer().toHtml', async () => {
  const src = await read('app/components/chat/AnswerBlock.vue')
  assert.match(src, /createStreamingRenderer/, 'phải tạo streaming renderer')
  assert.match(src, /streamingRenderer\.toHtml\(/, 'nhánh streaming phải gọi toHtml')
  // Không còn md.render trực tiếp trên toàn bộ content ở nhánh streaming
  assert.doesNotMatch(src, /if \(props\.data\.streaming\) \{\s*const html = md\.render\(props\.data\.content\)/,
    'nhánh streaming không còn md.render(toàn bộ content) trực tiếp')
})
