import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { createStreamBuffer } from '../app/lib/streamBuffer.ts'
import { pickScheduleMode } from '../app/lib/rafScheduler.ts'

const root = new URL('../', import.meta.url)
const read = (p: string) => readFile(new URL(p, root), 'utf8')

// Scheduler giả: lưu callback, cho phép trigger tay. cancel đánh dấu đã huỷ.
function fakeScheduler() {
  let pending: (() => void) | null = null
  let cancelled = 0
  return {
    schedule: (cb: () => void) => { pending = cb; return { id: 1 } },
    cancel: (_h: unknown) => { pending = null; cancelled++ },
    tick: () => { const cb = pending; pending = null; cb?.() },
    cancelled: () => cancelled,
    hasPending: () => pending !== null,
  }
}

test('gom nhiều push thành 1 commit khi flush', () => {
  const s = fakeScheduler()
  const commits: string[] = []
  const buf = createStreamBuffer({ commit: d => commits.push(d), schedule: s.schedule, cancel: s.cancel })
  buf.push('a'); buf.push('b'); buf.push('c')
  assert.deepEqual(commits, [], 'chưa flush thì chưa commit')
  s.tick()
  assert.deepEqual(commits, ['abc'], 'flush gom 3 token thành 1 commit')
})

test('nhiều đợt flush -> delta đúng từng đợt, không trùng/mất', () => {
  const s = fakeScheduler()
  const commits: string[] = []
  const buf = createStreamBuffer({ commit: d => commits.push(d), schedule: s.schedule, cancel: s.cancel })
  buf.push('a'); buf.push('b'); s.tick()
  buf.push('c'); buf.push('d'); s.tick()
  assert.deepEqual(commits, ['ab', 'cd'])
})

test('flush khi delta rỗng không commit', () => {
  const s = fakeScheduler()
  const commits: string[] = []
  const buf = createStreamBuffer({ commit: d => commits.push(d), schedule: s.schedule, cancel: s.cancel })
  buf.flush()
  s.tick()
  assert.deepEqual(commits, [])
})

test('dispose huỷ lịch đang chờ và không commit', () => {
  const s = fakeScheduler()
  const commits: string[] = []
  const buf = createStreamBuffer({ commit: d => commits.push(d), schedule: s.schedule, cancel: s.cancel })
  buf.push('a'); buf.push('b')
  buf.dispose()
  assert.equal(s.cancelled(), 1, 'cancel được gọi')
  assert.equal(s.hasPending(), false)
  s.tick()
  assert.deepEqual(commits, [], 'sau dispose không commit')
})

test('push lại sau flush thì đặt lịch mới (không kẹt)', () => {
  const s = fakeScheduler()
  const commits: string[] = []
  const buf = createStreamBuffer({ commit: d => commits.push(d), schedule: s.schedule, cancel: s.cancel })
  buf.push('a'); s.tick()
  buf.push('b')
  assert.equal(s.hasPending(), true, 'có lịch mới sau khi đã flush')
  s.tick()
  assert.deepEqual(commits, ['a', 'b'])
})

test('pickScheduleMode: dùng raf khi có window và tab hiện', () => {
  assert.equal(pickScheduleMode({ hasWindow: true, hidden: false }), 'raf')
})
test('pickScheduleMode: dùng timeout khi không có window (SSR)', () => {
  assert.equal(pickScheduleMode({ hasWindow: false, hidden: false }), 'timeout')
})
test('pickScheduleMode: dùng timeout khi tab ẩn', () => {
  assert.equal(pickScheduleMode({ hasWindow: true, hidden: true }), 'timeout')
})

test('chat.ts: token path dùng buffer.push, không += streamingText, có dispose', async () => {
  const src = await read('app/stores/chat.ts')
  assert.match(src, /buffer\.push\(/, 'token phải đẩy vào buffer')
  assert.doesNotMatch(src, /streamingText\.value \+= payload\.token/, 'không còn += trực tiếp mỗi token')
  assert.match(src, /buffer\.dispose\(/, 'phải dispose buffer khi kết thúc')
  assert.match(src, /createStreamBuffer/, 'phải tạo buffer')
})
