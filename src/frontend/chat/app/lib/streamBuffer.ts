export interface StreamBufferOptions {
  // Ghi delta đã gom (store: streamingText.value += delta).
  commit: (delta: string) => void
  // Đặt lịch flush; trả handle để cancel.
  schedule: (cb: () => void) => unknown
  // Huỷ lịch đã đặt.
  cancel: (handle: unknown) => void
}

export interface StreamBuffer {
  push: (token: string) => void
  flush: () => void
  dispose: () => void
}

// Gom token vào một chuỗi delta, flush tối đa 1 lần mỗi lần scheduler kích hoạt.
export function createStreamBuffer(opts: StreamBufferOptions): StreamBuffer {
  let delta = ''
  let handle: unknown = null

  function flush() {
    handle = null
    if (!delta) return
    const chunk = delta
    delta = ''
    opts.commit(chunk)
  }

  function push(token: string) {
    delta += token
    if (handle === null) {
      handle = opts.schedule(flush)
    }
  }

  function dispose() {
    if (handle !== null) {
      opts.cancel(handle)
      handle = null
    }
    delta = ''
  }

  return { push, flush, dispose }
}
