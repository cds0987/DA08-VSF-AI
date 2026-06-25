import assert from 'node:assert/strict'
import test from 'node:test'
import {
  formatRelativeTime,
  groupByTime,
  notificationKind,
} from '../app/lib/notificationFormat.ts'

const NOW = new Date('2026-06-25T12:00:00')
const iso = (d: Date) => d.toISOString()
const ago = (sec: number) => iso(new Date(NOW.getTime() - sec * 1000))

test('formatRelativeTime: biên Vừa xong / phút / giờ / ngày', () => {
  assert.equal(formatRelativeTime(ago(10), NOW), 'Vừa xong')
  assert.equal(formatRelativeTime(ago(44), NOW), 'Vừa xong')
  assert.equal(formatRelativeTime(ago(60), NOW), '1 phút trước')
  assert.equal(formatRelativeTime(ago(59 * 60), NOW), '59 phút trước')
  assert.equal(formatRelativeTime(ago(2 * 3600), NOW), '2 giờ trước')
  assert.equal(formatRelativeTime(ago(3 * 86400), NOW), '3 ngày trước')
})

test('formatRelativeTime: quá 7 ngày -> ngày tuyệt đối (không phải "x ngày trước")', () => {
  const out = formatRelativeTime(ago(10 * 86400), NOW)
  assert.doesNotMatch(out, /trước/)
})

test('formatRelativeTime: mốc tương lai (lệch đồng hồ) -> Vừa xong', () => {
  assert.equal(formatRelativeTime(iso(new Date(NOW.getTime() + 5000)), NOW), 'Vừa xong')
})

test('groupByTime: chia Hôm nay / Hôm qua / Trước đó, bỏ nhóm rỗng, giữ thứ tự', () => {
  const items = [
    { id: 'a', created_at: ago(3600), event: 'doc_new' },       // hôm nay
    { id: 'b', created_at: ago(26 * 3600), event: 'doc_new' },  // hôm qua
    { id: 'c', created_at: ago(5 * 86400), event: 'doc_new' },  // trước đó
  ]
  const groups = groupByTime(items, NOW)
  assert.deepEqual(groups.map((g) => g.key), ['today', 'yesterday', 'earlier'])
  assert.deepEqual(groups.map((g) => g.label), ['Hôm nay', 'Hôm qua', 'Trước đó'])
  assert.equal(groups[0].items[0].id, 'a')
})

test('groupByTime: nhóm rỗng bị loại', () => {
  const items = [{ id: 'a', created_at: ago(3600), event: 'doc_new' }]
  const groups = groupByTime(items, NOW)
  assert.deepEqual(groups.map((g) => g.key), ['today'])
})

test('notificationKind: map đúng loại + fallback generic', () => {
  assert.equal(notificationKind('doc_new').tone, 'indigo')
  assert.equal(notificationKind('leave_approved').tone, 'emerald')
  assert.equal(notificationKind('leave_rejected').tone, 'rose')
  assert.equal(notificationKind('leave_cancelled').tone, 'slate')
  assert.equal(notificationKind('leave_request_new').tone, 'amber')
  assert.equal(notificationKind('something_unknown').key, 'generic')
  assert.equal(notificationKind(undefined).key, 'generic')
})
