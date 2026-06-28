// Quyết định CÁCH xem 1 tài liệu theo đuôi tệp — 1 nguồn sự thật, KHÔNG hardcode PDF.
// Tách riêng (thuần, không phụ thuộc Vue) để test được và để SourcePanel chỉ việc dispatch.
//
//   pdf       -> PDF.js viewer (blob same-origin)
//   office    -> officeparser -> HTML (docx/pptx)
//   sheet     -> SheetJS -> HTML table (xlsx/xls/csv) — officeparser render bảng tính bị hỏng
//   markdown  -> markdown-it -> HTML
//   html      -> HTML gốc (đã DOMPurify) trong iframe sandbox sẵn có
//   text      -> hiển thị thô (txt)
//   image     -> <img> (ảnh trình duyệt render được)
//   fallback  -> thẻ đẹp "Mở/Tải tài liệu gốc" (tif/tiff + type lạ; KHÔNG render được tại đây)

export type ViewerMode = 'pdf' | 'office' | 'sheet' | 'html' | 'text' | 'markdown' | 'image' | 'fallback'

const MODE_BY_EXT: Record<string, ViewerMode> = {
  pdf: 'pdf',
  docx: 'office', pptx: 'office',
  // Bảng tính dùng SheetJS (officeparser chỉ trả tên sheet.xml, không dựng được bảng).
  xlsx: 'sheet', xls: 'sheet', csv: 'sheet',
  txt: 'text',
  md: 'markdown',
  htm: 'html', html: 'html',
  png: 'image', jpg: 'image', jpeg: 'image', gif: 'image', bmp: 'image', webp: 'image',
  // tif, tiff: trình duyệt KHÔNG render -> fallback có chủ đích.
}

/** Đuôi tệp -> chế độ xem. Chuẩn hoá hoa/thường + dấu '.' đầu. Lạ/rỗng -> 'fallback' (không câm). */
export function resolveViewerMode(fileType?: string | null): ViewerMode {
  const ext = (fileType ?? '').trim().toLowerCase().replace(/^\./, '')
  return MODE_BY_EXT[ext] ?? 'fallback'
}
