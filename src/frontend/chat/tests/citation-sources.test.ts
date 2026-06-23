import assert from 'node:assert/strict'
import test from 'node:test'
import { buildCitationSources } from '../app/lib/utils.ts'
import type { Citation } from '../app/types/index.ts'

function cite(partial: Partial<Citation>): Citation {
  return {
    id: partial.id ?? Math.random().toString(36).slice(2),
    document_id: partial.document_id ?? 'doc',
    document: partial.document ?? 'doc.pdf',
    caption: partial.caption ?? '',
    heading_path: partial.heading_path ?? [],
    ...partial,
  }
}

test('deduplicates citations by document and numbers them in first-appearance order', () => {
  const citations = [
    cite({ document_id: 'a', document: 'A.pdf', ref: 1, score: 0.5 }),
    cite({ document_id: 'b', document: 'B.docx', ref: 2, score: 0.9 }),
    cite({ document_id: 'a', document: 'A.pdf', ref: 3, score: 0.8 }),
  ]
  const { sources } = buildCitationSources(citations)
  assert.equal(sources.length, 2)
  assert.equal(sources[0].number, 1)
  assert.equal(sources[0].citation.document, 'A.pdf')
  assert.equal(sources[1].number, 2)
  assert.equal(sources[1].citation.document, 'B.docx')
})

test('picks the highest-scoring chunk as the document representative', () => {
  const citations = [
    cite({ document_id: 'a', document: 'A.pdf', ref: 1, score: 0.4, caption: 'low' }),
    cite({ document_id: 'a', document: 'A.pdf', ref: 2, score: 0.95, caption: 'high' }),
  ]
  const { sources } = buildCitationSources(citations)
  assert.equal(sources.length, 1)
  assert.equal(sources[0].citation.caption, 'high')
})

test('maps both ref values and 1-based indexes to the source number', () => {
  const citations = [
    cite({ document_id: 'a', document: 'A.pdf', ref: 7 }),
    cite({ document_id: 'b', document: 'B.pdf', ref: 9 }),
    cite({ document_id: 'a', document: 'A.pdf', ref: 11 }),
  ]
  const { refToNumber } = buildCitationSources(citations)
  // by ref value
  assert.equal(refToNumber[7], 1)
  assert.equal(refToNumber[9], 2)
  assert.equal(refToNumber[11], 1)
  // by 1-based index fallback (LLM emits [1],[2],[3])
  assert.equal(refToNumber[1], 1)
  assert.equal(refToNumber[2], 2)
  assert.equal(refToNumber[3], 1)
})

test('handles missing document_id by falling back to document name', () => {
  const citations = [
    cite({ document_id: '', document: 'Same.pdf', ref: 1 }),
    cite({ document_id: '', document: 'Same.pdf', ref: 2 }),
  ]
  const { sources } = buildCitationSources(citations)
  assert.equal(sources.length, 1)
})

test('returns empty result for no citations', () => {
  const { sources, refToNumber } = buildCitationSources(undefined)
  assert.deepEqual(sources, [])
  assert.deepEqual(refToNumber, {})
})
