import type { ClassValue } from "clsx"
import { clsx } from "clsx"
import { twMerge } from "tailwind-merge"
import type { Citation } from "~/types"

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

/**
 * Dọn nhãn citation: gộp khoảng trắng + bóc các tiền tố đánh số/bullet vô nghĩa ở
 * đầu (vd "1. ", "1) ", "a. ", "- ", "• ") — caption thường là 1 dòng list thô cắt
 * từ tài liệu nên hay dính số thứ tự, làm nhãn đọc như "1. Lập, cập nhật,…".
 */
export function cleanCitationLabel(text?: string | null): string {
  let clean = (text ?? '').replace(/\s+/g, ' ').trim()
  // Bóc lặp để xử lý lồng nhau (vd "1. a) ..."); dừng khi không còn bóc được nữa.
  let prev = ''
  while (clean && clean !== prev) {
    prev = clean
    clean = clean.replace(/^(?:\d+|[a-zA-Z])[.)\]]\s+|^[-–—•*]\s+/, '').trim()
  }
  return clean
}

/** Vài chữ đầu nội dung cho chip citation (gợi tò mò). Cắt theo ranh giới từ,
 * ngắn (~18 ký tự). Rỗng -> "Nguồn". */
export function citationTeaser(text?: string | null): string {
  const clean = cleanCitationLabel(text)
  if (!clean) return 'Nguồn'
  if (clean.length <= 18) return clean
  const cut = clean.slice(0, 18)
  const lastSpace = cut.lastIndexOf(' ')
  return (lastSpace > 8 ? cut.slice(0, lastSpace) : cut).trimEnd() + '…'
}

/** 1 nguồn đã chuẩn hóa: số thứ tự hiển thị + citation đại diện (chunk điểm cao nhất). */
export interface NormalizedSource {
  number: number
  citation: Citation
}

/**
 * Gom citation theo TÀI LIỆU (dedup) cho UI nguồn kiểu DeepSeek:
 *  - identity = document_id (nếu có) else tên tài liệu -> cùng tài liệu chỉ 1 nguồn;
 *  - đại diện = chunk có score cao nhất (đoạn liên quan nhất để mở trong SourcePanel);
 *  - đánh số theo THỨ TỰ XUẤT HIỆN ĐẦU TIÊN trong mảng;
 *  - refToNumber map cả ref-value LLM phát (vd [7]) LẪN index 1-based ([1],[2],[3]) -> số nguồn.
 * Rỗng/undefined -> { sources: [], refToNumber: {} }.
 */
export function buildCitationSources(
  citations?: Citation[],
): { sources: NormalizedSource[]; refToNumber: Record<number, number> } {
  const sources: NormalizedSource[] = []
  const refToNumber: Record<number, number> = {}
  if (!citations || !citations.length) return { sources, refToNumber }

  const posByKey = new Map<string, number>()
  citations.forEach((citation, i) => {
    const key = (citation.document_id?.trim() || citation.document?.trim() || '').toLowerCase()
    let pos = posByKey.get(key)
    if (pos === undefined) {
      pos = sources.length
      posByKey.set(key, pos)
      sources.push({ number: pos + 1, citation })
    } else if ((citation.score ?? -Infinity) > (sources[pos].citation.score ?? -Infinity)) {
      // Giữ chunk điểm cao nhất làm đại diện (number không đổi vì theo first-appearance).
      sources[pos] = { number: pos + 1, citation }
    }
    const num = pos + 1
    refToNumber[i + 1] = num                                   // fallback: LLM phát [1],[2],[3]
    if (typeof citation.ref === 'number') refToNumber[citation.ref] = num  // ưu tiên ref-value thật
  })

  return { sources, refToNumber }
}

/** Nhóm loại tệp (để chọn icon/màu) — KHÔNG hardcode PDF, phủ đủ định dạng hỗ trợ. */
export type CitationFileGroup = 'pdf' | 'doc' | 'text' | 'web' | 'sheet' | 'slide' | 'image' | 'unknown'

const FILE_GROUP: Record<string, CitationFileGroup> = {
  pdf: 'pdf',
  docx: 'doc',
  txt: 'text', md: 'text',
  htm: 'web', html: 'web',
  csv: 'sheet', xls: 'sheet', xlsx: 'sheet',
  pptx: 'slide',
  bmp: 'image', gif: 'image', jpeg: 'image', jpg: 'image', png: 'image', tif: 'image', tiff: 'image', webp: 'image',
}

/** Đuôi tệp (lowercase) + nhóm loại từ tên tài liệu. Không có đuôi -> group 'unknown'. */
export function citationFileKind(documentName?: string | null): { ext: string; group: CitationFileGroup } {
  const name = (documentName ?? '').trim()
  const ext = name.includes('.') ? name.split('.').pop()!.toLowerCase() : ''
  return { ext, group: FILE_GROUP[ext] ?? 'unknown' }
}

/** Metadata phụ cho thẻ nguồn. Trả '' khi thiếu -> KHÔNG bao giờ render undefined/null/NaN. */
export function sourceMeta(citation: Citation): { section: string; page: string; relevance: string } {
  return {
    section: citationHeadingPath(citation.heading_path ?? [], citation.document).join(' › '),
    page: citation.page_number ? `Đoạn ${citation.page_number}` : '',
    relevance: formatRelevance(citation.score),
  }
}
