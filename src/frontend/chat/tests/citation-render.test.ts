import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('../', import.meta.url)
const read = (path: string) => readFile(new URL(path, root), 'utf8')

test('AnswerBlock renders slim numbered citation pills wired to the source panel', async () => {
  const block = await read('app/components/chat/AnswerBlock.vue')

  // Numbered-pill pipeline (replaces the old logo + teaser chip).
  assert.match(block, /buildCitationSources/)
  assert.match(block, /const \{ refToNumber \} = citationSources\.value/)
  assert.match(block, /class="citation-ref[^"]*" role="button" tabindex="0" aria-label="\$\{label\}" data-ref="\$\{marker\}">\$\{num\}</)
  // One pill per source: dedup within a [N][N] run by source number.
  assert.match(block, /const seen = new Set<number>\(\)/)
  assert.match(block, /seen\.has\(num\)/)
  // Drop fabricated LLM refs that don't resolve to a real citation.
  assert.match(block, /if \(!cit \|\| num === undefined \|\| seen\.has\(num\)\) continue/)

  // Click + keyboard open the SPECIFIC cited chunk via data-ref.
  assert.match(block, /function openMarker\(el: HTMLElement\)/)
  assert.match(block, /resolveRef\(parseInt\(el\.dataset\.ref \?\? ''\)\)/)
  assert.match(block, /if \(cit\) emit\('open-citation', cit\)/)
  assert.match(block, /@click="handleContentClick"/)
  assert.match(block, /@keydown="handleContentKeydown"/)
  assert.match(block, /if \(e\.key !== 'Enter' && e\.key !== ' '\) return/)

  // Source cards: ONLY documents actually cited ([N] in the answer), not every retrieved chunk.
  assert.match(block, /const citedSources = computed/)
  assert.match(block, /citedSources\.length/)
  assert.match(block, /v-for="s in citedSources"/)
  assert.match(block, /@click="emit\('open-citation', s\.citation\)"/)
  assert.match(block, /\{\{ s\.number \}\}/)
  assert.match(block, /\{\{ s\.citation\.document \}\}/)
  // Right-side metadata (section / page / relevance %) removed — only the document name shows.
  assert.doesNotMatch(block, /sourceMeta/)
  // Keyboard focus ring on cards.
  assert.match(block, /focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500/)

  // Noisy hover popover + logo chip fully removed.
  assert.doesNotMatch(block, /Teleport/)
  assert.doesNotMatch(block, /popover/i)
  assert.doesNotMatch(block, /\/logo\.png/)
  assert.doesNotMatch(block, /activeCite/)
})
