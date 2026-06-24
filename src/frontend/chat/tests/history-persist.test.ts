import assert from 'node:assert/strict'
import test from 'node:test'
import { buildHistorySnapshot } from '../app/lib/historyPersist.ts'
import type { Conversation } from '../app/types/index.ts'

function conv(id: string, msgs: string[]): Conversation {
  return {
    id,
    title: id,
    updatedAt: '2026-06-24T00:00:00.000Z',
    bucket: 'today',
    messages: msgs.map((c, i) => ({ id: `${id}-${i}`, role: 'user', content: c, timestamp: '' })),
  } as Conversation
}

test('clone SÂU conversation hiện tại (sửa source không đổi snapshot)', () => {
  const cur = conv('a', ['x'])
  const snap = buildHistorySnapshot([cur], 'a', [])
  cur.messages[0].content = 'MUTATED'
  cur.title = 'MUTATED'
  assert.equal(snap[0].messages[0].content, 'x', 'message đã được clone')
  assert.equal(snap[0].title, 'a', 'conversation đã được clone')
})

test('conversation KHÁC được tái dùng từ prevSnapshot (cùng reference)', () => {
  const a = conv('a', ['x'])
  const bPrev = conv('b', ['y'])
  const prev = [bPrev]
  const b = conv('b', ['y'])
  const snap = buildHistorySnapshot([a, b], 'a', prev)
  const snapB = snap.find(c => c.id === 'b')!
  assert.equal(snapB, bPrev, 'conversation b tái dùng object từ prevSnapshot (===)')
})

test('conversation không có trong prev -> được clone (không undefined)', () => {
  const a = conv('a', ['x'])
  const b = conv('b', ['y'])
  const snap = buildHistorySnapshot([a, b], 'a', [])
  const snapB = snap.find(c => c.id === 'b')!
  assert.ok(snapB, 'b có mặt')
  assert.notEqual(snapB, b, 'b được clone, không phải reference gốc')
  assert.equal(snapB.messages[0].content, 'y')
})

test('giữ nguyên thứ tự của conversations', () => {
  const snap = buildHistorySnapshot([conv('a', []), conv('b', []), conv('c', [])], 'b', [])
  assert.deepEqual(snap.map(c => c.id), ['a', 'b', 'c'])
})

test('currentId null -> mọi conversation clone/tái dùng, không lỗi', () => {
  const a = conv('a', ['x'])
  const snap = buildHistorySnapshot([a], null, [])
  assert.notEqual(snap[0], a)
  assert.equal(snap[0].messages[0].content, 'x')
})
