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
