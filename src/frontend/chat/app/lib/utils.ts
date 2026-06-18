import type { ClassValue } from "clsx"
import { clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const NO_HEADING_PLACEHOLDER = '(no heading)'

/**
 * Heading path để hiển thị ở citation. Bỏ placeholder "(no heading)" và phần trùng
 * tên tài liệu (UI đã hiển thị tên file riêng -> tránh trùng tên). Trả [] nếu không
 * còn breadcrumb thật nào để hiện.
 */
export function citationHeadingPath(headingPath: string[], documentName?: string | null): string[] {
  const docName = documentName?.trim().toLowerCase()
  return headingPath.filter((part) => {
    const value = part.trim().toLowerCase()
    return value.length > 0 && part !== NO_HEADING_PLACEHOLDER && value !== docName
  })
}

/** Điểm liên quan (0..1) -> chuỗi phần trăm cho chip citation. '' nếu không hợp lệ. */
export function formatRelevance(score?: number | null): string {
  if (typeof score !== 'number' || Number.isNaN(score)) return ''
  const pct = Math.round(Math.max(0, Math.min(1, score)) * 100)
  return `${pct}%`
}

/** Vài chữ đầu nội dung cho chip citation (gợi tò mò). Cắt theo ranh giới từ,
 * ngắn (~18 ký tự). Rỗng -> "Nguồn". */
export function citationTeaser(text?: string | null): string {
  if (!text) return 'Nguồn'
  const clean = text.replace(/\s+/g, ' ').trim()
  if (!clean) return 'Nguồn'
  if (clean.length <= 18) return clean
  const cut = clean.slice(0, 18)
  const lastSpace = cut.lastIndexOf(' ')
  return (lastSpace > 8 ? cut.slice(0, lastSpace) : cut).trimEnd() + '…'
}
