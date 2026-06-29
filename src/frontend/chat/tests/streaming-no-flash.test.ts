import assert from 'node:assert/strict'
import { readFile, access } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('../', import.meta.url)
const read = (path: string) => readFile(new URL(path, root), 'utf8')
const exists = (path: string) => access(new URL(path, root)).then(() => true, () => false)

// Bug: khi stream xong, câu trả lời bị "flash" vì swap StreamingBlock -> AnswerBlock
// (unmount/mount). Fix: dùng CHUNG AnswerBlock cho cả streaming + final, với turnKey ổn
// định -> Vue PATCH cùng node thay vì remount. Các test dưới khoá invariant của fix.

test('StreamingBlock bị gỡ bỏ (không còn 2 component render câu trả lời)', async () => {
  assert.equal(await exists('app/components/chat/StreamingBlock.vue'), false)
  const chatMessages = await read('app/components/chat/ChatMessages.vue')
  assert.doesNotMatch(chatMessages, /StreamingBlock/)
})

test('ChatMessages render placeholder-stream bằng AnswerBlock với turnKey ổn định', async () => {
  const f = await read('app/components/chat/ChatMessages.vue')
  // prop key ổn định cho cả lượt
  assert.match(f, /streamingTurnKey:\s*string/)
  // placeholder dùng chung turnKey + cờ streaming
  assert.match(f, /turnKey:\s*props\.streamingTurnKey/)
  assert.match(f, /streaming:\s*true/)
  assert.match(f, /content:\s*props\.streamingText/)
  // v-for key ưu tiên turnKey -> placeholder & final khớp key -> patch, không remount
  assert.match(f, /:key="message\.turnKey \?\? message\.id"/)
  // chỉ AnswerBlock render assistant (cả streaming)
  assert.match(f, /import AnswerBlock from/)
})

test('placeholder-stream mang sẵn trace/plan -> MessageSteps hiện từ đầu (không dịch lúc done)', async () => {
  const f = await read('app/components/chat/ChatMessages.vue')
  assert.match(f, /trace:\s*props\.traceLog/)
  assert.match(f, /models:\s*props\.modelsUsed/)
  assert.match(f, /thoughts:\s*props\.thoughts/)
  assert.match(f, /plan:\s*props\.plan \?\? undefined/)
})

test('AnswerBlock: lúc streaming render thô, KHÔNG inject chip, ẩn toolbar; KHÔNG còn con trỏ', async () => {
  const f = await read('app/components/chat/AnswerBlock.vue')
  // nhánh streaming trong renderedContent
  assert.match(f, /if \(props\.data\.streaming\)/)
  // toolbar feedback gate theo !data.streaming (có thể kèm điều kiện khác, vd && !isProactive)
  assert.match(f, /v-if="!data\.streaming\b/)
  // Con trỏ stream đã được gỡ bỏ hoàn toàn (không inject span, không CSS blink)
  assert.doesNotMatch(f, /streaming-cursor/)
  assert.doesNotMatch(f, /@keyframes streaming-blink/)
})

test('store: cấp turnKey lượt ở đầu ask và gắn vào message cuối', async () => {
  const f = await read('app/stores/chat.ts')
  assert.match(f, /const pendingAssistantId = ref\(''\)/)
  assert.match(f, /pendingAssistantId\.value = 'a-' \+ Date\.now\(\)/)
  // message cuối dùng CÙNG turnKey với placeholder -> Vue patch cùng node
  assert.match(f, /turnKey:\s*pendingAssistantId\.value/)
  assert.match(f, /\n\s*pendingAssistantId,\n/) // được export ra cho page truyền xuống
})

test('ChatMessage type có streaming? và turnKey?', async () => {
  const f = await read('app/types/index.ts')
  assert.match(f, /turnKey\?:\s*string/)
  assert.match(f, /streaming\?:\s*boolean/)
})

test('cả 2 page truyền streaming-turn-key xuống ChatMessages', async () => {
  for (const page of ['app/pages/chat/index.vue', 'app/pages/chat/[id].vue']) {
    const f = await read(page)
    assert.match(f, /:streaming-turn-key="chat\.pendingAssistantId"/, `${page} thiếu streaming-turn-key`)
  }
})
