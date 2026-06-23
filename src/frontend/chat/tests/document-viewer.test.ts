import assert from 'node:assert/strict'
import test from 'node:test'
import { resolveViewerMode } from '../app/lib/documentViewer.ts'

test('PDF -> pdf', () => {
  assert.equal(resolveViewerMode('pdf'), 'pdf')
})

test('office docs (officeparser) -> office', () => {
  for (const t of ['docx', 'pptx', 'xlsx', 'csv']) {
    assert.equal(resolveViewerMode(t), 'office', `${t} phải là office`)
  }
})

test('txt -> text, md -> markdown', () => {
  assert.equal(resolveViewerMode('txt'), 'text')
  assert.equal(resolveViewerMode('md'), 'markdown')
})

test('htm/html -> html (preview an toàn qua sandbox sẵn có)', () => {
  assert.equal(resolveViewerMode('htm'), 'html')
  assert.equal(resolveViewerMode('html'), 'html')
})

test('ảnh trình duyệt render được -> image', () => {
  for (const t of ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp']) {
    assert.equal(resolveViewerMode(t), 'image', `${t} phải là image`)
  }
})

test('xls/tif/tiff (không render được) -> fallback', () => {
  for (const t of ['xls', 'tif', 'tiff']) {
    assert.equal(resolveViewerMode(t), 'fallback', `${t} phải là fallback`)
  }
})

test('type lạ / rỗng / nullish -> fallback (không bao giờ câm)', () => {
  for (const t of ['', '   ', null, undefined, 'exe', 'zip', 'unknown']) {
    assert.equal(resolveViewerMode(t as string | null | undefined), 'fallback')
  }
})

test('chuẩn hoá: hoa/thường + dấu chấm đầu', () => {
  assert.equal(resolveViewerMode('PDF'), 'pdf')
  assert.equal(resolveViewerMode('.DOCX'), 'office')
  assert.equal(resolveViewerMode('.PNG'), 'image')
  assert.equal(resolveViewerMode('HTML'), 'html')
})

test('phủ ĐỦ bộ định dạng yêu cầu, không cái nào trả về undefined', () => {
  const required = ['bmp', 'csv', 'docx', 'gif', 'htm', 'html', 'jpeg', 'jpg', 'md', 'pdf',
    'png', 'pptx', 'tif', 'tiff', 'txt', 'webp', 'xls', 'xlsx']
  const valid = new Set(['pdf', 'office', 'html', 'text', 'markdown', 'image', 'fallback'])
  for (const t of required) {
    const mode = resolveViewerMode(t)
    assert.ok(valid.has(mode), `${t} -> ${mode} phải là 1 mode hợp lệ`)
  }
})
