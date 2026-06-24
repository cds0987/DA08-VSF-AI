import assert from 'node:assert/strict'
import test from 'node:test'
import { findLastBlockBoundary } from '../app/lib/streamingMarkdown.ts'

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
