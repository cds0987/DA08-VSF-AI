import assert from 'node:assert/strict'
import test from 'node:test'

import { previewKindFromMime } from '../app/lib/documentPreview'

test('pdf mime -> pdf', () => {
  assert.equal(previewKindFromMime('application/pdf'), 'pdf')
})

test('image mime -> image', () => {
  assert.equal(previewKindFromMime('image/png'), 'image')
  assert.equal(previewKindFromMime('image/jpeg'), 'image')
})

test('text mime (kèm charset) -> text', () => {
  assert.equal(previewKindFromMime('text/plain; charset=utf-8'), 'text')
})

test('office mime KHÔNG còn map xuống download/unknown nhầm -> unknown chỉ khi không render được', () => {
  assert.equal(previewKindFromMime('application/octet-stream'), 'unknown')
})
