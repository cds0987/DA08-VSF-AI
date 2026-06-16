import type { ClassValue } from "clsx"
import { clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const NO_HEADING_PLACEHOLDER = '(no heading)'

/**
 * Heading path để hiển thị ở citation. Tài liệu cũ (ingest trước fix) có thể chứa
 * placeholder "(no heading)" -> thay bằng tên tài liệu. Trả [] nếu không có gì để hiện.
 */
export function citationHeadingPath(headingPath: string[], documentName?: string | null): string[] {
  return headingPath
    .map(part => (part === NO_HEADING_PLACEHOLDER ? (documentName ?? '') : part))
    .filter(part => part.length > 0)
}
