// Trả index NGAY SAU '\n\n' cuối cùng KHÔNG nằm trong fenced code block (``` hoặc ~~~).
// Quét theo dòng, lật cờ inFence khi gặp dòng mở/đóng fence. Ranh giới hợp lệ = ranh giới
// giữa 2 block (một dòng trống) khi KHÔNG ở trong fence.
export function findLastBlockBoundary(src: string): number {
  const lines = src.split('\n')
  let inFence = false
  let fenceMarker = ''
  let pos = 0           // offset đầu dòng hiện tại trong src
  let lastBoundary = 0
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trimStart()
    const m = trimmed.match(/^(```+|~~~+)/)
    if (m) {
      if (!inFence) { inFence = true; fenceMarker = m[1][0] }
      else if (m[1][0] === fenceMarker) { inFence = false; fenceMarker = '' }
    } else if (!inFence && line.trim() === '' && i > 0 && i < lines.length - 1) {
      // Dòng trống THẬT ngoài fence = ranh giới block. Bỏ phần tử '' CUỐI (artifact của '\n'
      // kết thúc chuỗi, không phải dòng trống thật) bằng điều kiện i < lines.length - 1.
      // Boundary = offset NGAY SAU dòng trống này.
      lastBoundary = pos + line.length + 1   // +1 cho '\n' kết thúc dòng trống
    }
    pos += line.length + 1                   // +1 cho '\n' giữa các dòng
  }
  return lastBoundary
}
