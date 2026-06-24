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
