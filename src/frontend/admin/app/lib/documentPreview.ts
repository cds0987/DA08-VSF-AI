export type PreviewMode = 'pdf' | 'image' | 'text' | 'download'

const IMAGE_TYPES = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp'])
const TEXT_TYPES = new Set(['txt', 'md', 'csv'])

// Quyết định cách render file trong khung viewer nhúng. Khớp _INLINE_TYPES của
// document-service (get_document_file_stream_use_case.py). Office/nhị phân -> 'download'.
export function previewMode(fileType: string): PreviewMode {
  const ext = fileType.trim().toLowerCase().replace(/^\./, '')
  if (ext === 'pdf') return 'pdf'
  if (IMAGE_TYPES.has(ext)) return 'image'
  if (TEXT_TYPES.has(ext)) return 'text'
  return 'download'
}

export type PreviewKind = 'pdf' | 'image' | 'text' | 'unknown'

// Quyết định cách render trong viewer theo MIME của blob server trả về (/file/preview).
// Office đã được server convert sang application/pdf -> 'pdf'. Decouple FE khỏi đuôi file.
export function previewKindFromMime(mime: string): PreviewKind {
  const m = (mime || '').split(';')[0]!.trim().toLowerCase()
  if (m === 'application/pdf') return 'pdf'
  if (m.startsWith('image/')) return 'image'
  if (m.startsWith('text/')) return 'text'
  return 'unknown'
}
