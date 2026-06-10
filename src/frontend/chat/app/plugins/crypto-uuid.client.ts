// Polyfill crypto.randomUUID cho NON-SECURE context (HTTP).
// crypto.randomUUID chỉ tồn tại khi secure context (HTTPS hoặc localhost); demo chạy
// qua http://<IP> nên nó undefined -> "crypto.randomUUID is not a function".
// crypto.getRandomValues thì CÓ cả ở non-secure context -> dùng nó sinh UUID v4.
// .client.ts: chỉ chạy ở trình duyệt (server Node vốn đã có randomUUID).
export default defineNuxtPlugin(() => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID !== 'function') {
    ;(crypto as Crypto & { randomUUID: () => string }).randomUUID = function randomUUID(): string {
      const b = crypto.getRandomValues(new Uint8Array(16))
      b[6] = (b[6]! & 0x0f) | 0x40 // version 4
      b[8] = (b[8]! & 0x3f) | 0x80 // variant 10
      const h = Array.from(b, (x) => x.toString(16).padStart(2, '0'))
      return `${h.slice(0, 4).join('')}-${h.slice(4, 6).join('')}-${h.slice(6, 8).join('')}-${h.slice(8, 10).join('')}-${h.slice(10, 16).join('')}`
    }
  }
})
