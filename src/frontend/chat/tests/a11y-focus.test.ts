import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('../', import.meta.url)
const read = (path: string) => readFile(new URL(path, root), 'utf8')

// Khoá invariant a11y (Phase 5): mọi surface chat tương tác phải có focus ring nhìn thấy
// bằng bàn phím. Grep VỪA ĐỦ (chỉ assert có focus-visible:outline) — không khoá markup chi tiết.
const FOCUS_FILES = [
  'app/components/chat/ChatInput.vue',
  'app/components/chat/ActionableCard.vue',
  'app/components/chat/ApprovalReviewCard.vue',
  'app/components/chat/ProactiveSuggestionCard.vue',
]

for (const file of FOCUS_FILES) {
  test(`${file}: có focus ring nhìn thấy (focus-visible:outline)`, async () => {
    const src = await read(file)
    assert.match(src, /focus-visible:outline/, `${file} thiếu focus-visible:outline trên nút tương tác`)
  })
}
