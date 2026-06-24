import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { buildQuotedContent, truncateQuote, shouldShowAskButton } from '../app/lib/quote.ts'

const root = new URL('../', import.meta.url)
const read = (p: string) => readFile(new URL(p, root), 'utf8')

test('buildQuotedContent: prepends multiline blockquote + question', () => {
  assert.equal(
    buildQuotedContent({ messageId: 'm1', text: 'dòng 1\ndòng 2' }, '  Giải thích?  '),
    '> dòng 1\n> dòng 2\n\nGiải thích?',
  )
})

test('buildQuotedContent: no quote returns trimmed question', () => {
  assert.equal(buildQuotedContent(null, '  hỏi  '), 'hỏi')
  assert.equal(buildQuotedContent({ messageId: 'm', text: '   ' }, 'hỏi'), 'hỏi')
})

test('truncateQuote: collapses whitespace and adds ellipsis past max', () => {
  assert.equal(truncateQuote('a\n  b   c'), 'a b c')
  assert.equal(truncateQuote('x'.repeat(200), 10), 'xxxxxxxxxx…')
})

test('shouldShowAskButton: true only when all conditions hold', () => {
  const base = { text: 'hi', collapsed: false, inBotAnswer: true, inEditable: false, hasRect: true }
  assert.equal(shouldShowAskButton(base), true)
  assert.equal(shouldShowAskButton({ ...base, text: '   ' }), false)
  assert.equal(shouldShowAskButton({ ...base, collapsed: true }), false)
  assert.equal(shouldShowAskButton({ ...base, inBotAnswer: false }), false)
  assert.equal(shouldShowAskButton({ ...base, inEditable: true }), false)
  assert.equal(shouldShowAskButton({ ...base, hasRect: false }), false)
})

test('AnswerBlock: vùng markdown có data-bot-answer + data-message-id', async () => {
  const src = await read('app/components/chat/AnswerBlock.vue')
  assert.match(src, /data-bot-answer/)
  assert.match(src, /:data-message-id="data\.id"/)
})

test('SelectionAskButton: Teleport body, nhãn Hỏi FeatureMind, focus ring', async () => {
  const src = await read('app/components/chat/SelectionAskButton.vue')
  assert.match(src, /Teleport to="body"/)
  assert.match(src, /Hỏi FeatureMind/)
  assert.match(src, /focus-visible:outline/)
  assert.doesNotMatch(src, /Start writing/i)
})

test('ChatInput: chip trích dẫn (clear-quote, line-clamp, focus expose)', async () => {
  const src = await read('app/components/chat/ChatInput.vue')
  assert.match(src, /clear-quote/)
  assert.match(src, /line-clamp/)
  assert.match(src, /defineExpose/)
})
