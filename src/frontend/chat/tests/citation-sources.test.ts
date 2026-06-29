import assert from 'node:assert/strict'
import test from 'node:test'
import { buildCitationSources, compactCitedSources } from '../app/lib/utils.ts'
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

// --- compactCitedSources: nén số trích dẫn 1,2,5 -> 1,2,3 theo thứ tự xuất hiện ---

test('compacts cited refs to consecutive numbers by first-appearance order', () => {
  // 5 nguồn (ref 1..5), answer CHỈ trích [1], [2], [5] -> hiển thị phải nén thành 1,2,3.
  const citations = [
    cite({ document_id: 'a', document: 'A.docx', ref: 1 }),
    cite({ document_id: 'b', document: 'B.docx', ref: 2 }),
    cite({ document_id: 'c', document: 'C.docx', ref: 3 }),
    cite({ document_id: 'd', document: 'D.docx', ref: 4 }),
    cite({ document_id: 'e', document: 'E.docx', ref: 5 }),
  ]
  const content = 'Quản lý thẻ [1]. Phối hợp xử lý [2]. Mất thẻ thì báo ngay [5].'
  const { cited, markerToNumber } = compactCitedSources(content, citations)

  // chỉ 3 nguồn được trích, đánh số liên tục 1,2,3
  assert.equal(cited.length, 3)
  assert.deepEqual(cited.map(s => s.number), [1, 2, 3])
  assert.deepEqual(cited.map(s => s.citation.document), ['A.docx', 'B.docx', 'E.docx'])
  // marker thô [5] -> số hiển thị 3 (pill + danh sách khớp nhau)
  assert.equal(markerToNumber[1], 1)
  assert.equal(markerToNumber[2], 2)
  assert.equal(markerToNumber[5], 3)
})

test('numbers by ORDER OF APPEARANCE, not by ref value', () => {
  // Answer trích [5] TRƯỚC [2] -> [5] thành 1, [2] thành 2 (theo lần xuất hiện trong text).
  const citations = [
    cite({ document_id: 'a', document: 'A.docx', ref: 1 }),
    cite({ document_id: 'b', document: 'B.docx', ref: 2 }),
    cite({ document_id: 'e', document: 'E.docx', ref: 5 }),
  ]
  const { cited, markerToNumber } = compactCitedSources('Đầu tiên [5], sau đó [2].', citations)
  assert.deepEqual(cited.map(s => s.number), [1, 2])
  assert.deepEqual(cited.map(s => s.citation.document), ['E.docx', 'B.docx'])
  assert.equal(markerToNumber[5], 1)
  assert.equal(markerToNumber[2], 2)
})

test('dedups repeated marker + ignores fabricated refs with no source', () => {
  const citations = [cite({ document_id: 'a', document: 'A.docx', ref: 1 })]
  // [1] lặp lại -> 1 nguồn; [9] LLM bịa (không có source) -> bỏ.
  const { cited, markerToNumber } = compactCitedSources('Theo A [1]. Nhắc lại [1]. Bịa [9].', citations)
  assert.equal(cited.length, 1)
  assert.equal(cited[0].number, 1)
  assert.equal(markerToNumber[1], 1)
  assert.equal(markerToNumber[9], undefined)
})

test('returns empty when answer cites nothing', () => {
  const citations = [cite({ document_id: 'a', document: 'A.docx', ref: 1 })]
  const { cited, markerToNumber } = compactCitedSources('Không có trích dẫn nào.', citations)
  assert.deepEqual(cited, [])
  assert.deepEqual(markerToNumber, {})
})
