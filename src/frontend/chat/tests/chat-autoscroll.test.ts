import assert from 'node:assert/strict'
import test from 'node:test'
import { isNearBottom } from '../app/composables/useChatAutoScroll.ts'

test('isNearBottom: true khi trong ngưỡng, false khi user đã cuộn lên', () => {
  // scrollHeight - scrollTop - clientHeight = 1000-850-100 = 50 <= 64 -> true
  assert.equal(isNearBottom({ scrollHeight: 1000, scrollTop: 850, clientHeight: 100 }, 64), true)
  // = 1000-700-100 = 200 > 64 -> false
  assert.equal(isNearBottom({ scrollHeight: 1000, scrollTop: 700, clientHeight: 100 }, 64), false)
})

test('isNearBottom: đúng ngay tại đáy', () => {
  assert.equal(isNearBottom({ scrollHeight: 500, scrollTop: 400, clientHeight: 100 }, 96), true)
})

test('isNearBottom: ngưỡng mặc định 96', () => {
  assert.equal(isNearBottom({ scrollHeight: 1000, scrollTop: 810, clientHeight: 100 }), true)  // 90<=96
  assert.equal(isNearBottom({ scrollHeight: 1000, scrollTop: 800, clientHeight: 100 }), false) // 100>96
})

import { readFile } from 'node:fs/promises'
const root = new URL('../', import.meta.url)
const read = (p: string) => readFile(new URL(p, root), 'utf8')

for (const page of ['app/pages/chat/index.vue', 'app/pages/chat/[id].vue']) {
  test(`${page}: dùng sticky auto-scroll, không smooth-scroll mỗi token`, async () => {
    const src = await read(page)
    assert.match(src, /useChatAutoScroll/, 'page phải dùng composable chung')
    assert.doesNotMatch(src, /const smoothScrollToBottom = useDebounceFn/, 'bỏ smooth-scroll debounce theo token')
    assert.doesNotMatch(src, /scrollToBottom\('smooth'\)/, 'không smooth-scroll mỗi frame stream')
    assert.match(src, /scheduleAutoScroll\(\)/, 'watcher stream gọi auto-scroll có guard')
    assert.match(src, /scheduleInstantScroll\(\)/, 'load/đổi hội thoại/gửi tin vẫn cuộn tức thì')
  })
}
