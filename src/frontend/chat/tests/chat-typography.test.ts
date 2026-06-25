import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('../', import.meta.url)
const read = (path: string) => readFile(new URL(path, root), 'utf8')

test('AnswerBlock: bot answer tăng weight, màu giữ token (không ép trắng/đen)', async () => {
  const src = await read('app/components/chat/AnswerBlock.vue')

  // Tăng độ ĐẬM NÉT: font-medium ở wrapper + font-weight:500 trong style
  assert.match(src, /data-bot-answer[\s\S]*class="[^"]*\bfont-medium\b[^"]*\btext-slate-900\b[^"]*\bdark:text-foreground\b/)
  assert.match(src, /\.ai-response-markdown\s*\{[\s\S]*font-weight:\s*500/)
  // Màu prose vẫn theo token theme, KHÔNG hardcode trắng/đen
  assert.match(src, /--tw-prose-body:\s*var\(--foreground\)/)
  assert.match(src, /\bprose-strong:font-semibold\b/)
  assert.match(src, /\bprose-headings:font-semibold\b/)
  // Không được ép màu cực đại
  assert.doesNotMatch(src, /\btext-slate-950\b/)
  assert.doesNotMatch(src, /\bdark:text-white\b/)
  assert.doesNotMatch(src, /rgb\(255 255 255\)|rgb\(2 6 23\)/)
})

test('Thinking timeline: reasoning tăng weight, màu giữ token', async () => {
  const messageSteps = await read('app/components/chat/MessageSteps.vue')
  const pipeline = await read('app/components/chat/Pipeline.vue')
  const thoughtDetail = await read('app/components/chat/ThoughtDetail.vue')

  assert.match(thoughtDetail, /view\.summary[\s\S]*\bfont-medium\b[\s\S]*\bdark:text-muted-foreground\b/)
  for (const src of [messageSteps, pipeline, thoughtDetail]) {
    assert.match(src, /\bfont-medium\b/)
    // Không crank màu dark sang trắng
    assert.doesNotMatch(src, /\bdark:text-white\/\d/)
    assert.doesNotMatch(src, /\bdark:text-white\b/)
  }
})

test('User input + bubble: tăng weight, màu giữ token', async () => {
  const input = await read('app/components/chat/ChatInput.vue')
  const userBubble = await read('app/components/chat/UserBubble.vue')

  assert.match(input, /<textarea[\s\S]*class="[^"]*\bfont-medium\b[^"]*\btext-slate-800\b[^"]*\bdark:text-foreground\b/)
  assert.match(userBubble, /\bfont-medium\b/)
  assert.doesNotMatch(input, /\bdark:text-white\b/)
  assert.doesNotMatch(userBubble, /\bdark:text-white\b/)
})
