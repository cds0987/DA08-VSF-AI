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
