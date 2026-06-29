import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('../', import.meta.url)
const read = (path: string) => readFile(new URL(path, root), 'utf8')

// BUG: live Pipeline.vue vẽ mốc "Verify" theo placeholder verifyActive (isThinking && có tool),
// kể cả khi CHƯA có thought verify nào -> sau khi xong, MessageSteps.vue (persisted) chỉ vẽ group
// có thought thật nên Verify BIẾN MẤT. Placeholder rỗng đó là thứ tạo phantom -> phải đi.
test('Pipeline (live): KHÔNG còn placeholder Verify rỗng dựa trên verifyActive', async () => {
  const pipeline = await read('app/components/chat/Pipeline.vue')
  assert.doesNotMatch(pipeline, /verifyActive\s*&&\s*!verifyThoughts\.length/)
})
