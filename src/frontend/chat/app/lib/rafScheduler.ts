export interface ScheduleEnv {
  hasWindow: boolean
  hidden: boolean
}

// Thuần & test được: chọn cơ chế đặt lịch theo môi trường.
export function pickScheduleMode(env: ScheduleEnv): 'raf' | 'timeout' {
  return env.hasWindow && !env.hidden ? 'raf' : 'timeout'
}

const FALLBACK_MS = 100

// Scheduler mặc định: rAF khi ở client & tab hiện; ngược lại setTimeout.
// Lưu loại handle để cancel đúng API.
export function createRafScheduler() {
  function currentMode(): 'raf' | 'timeout' {
    return pickScheduleMode({
      hasWindow: typeof window !== 'undefined' && typeof requestAnimationFrame === 'function',
      hidden: typeof document !== 'undefined' && document.hidden,
    })
  }

  function schedule(cb: () => void): unknown {
    if (currentMode() === 'raf') {
      return { type: 'raf' as const, id: requestAnimationFrame(() => cb()) }
    }
    return { type: 'timeout' as const, id: setTimeout(cb, FALLBACK_MS) as unknown as number }
  }

  function cancel(handle: unknown): void {
    if (!handle || typeof handle !== 'object') return
    const h = handle as { type: 'raf' | 'timeout'; id: number }
    if (h.type === 'raf') cancelAnimationFrame(h.id)
    else clearTimeout(h.id)
  }

  return { schedule, cancel }
}
