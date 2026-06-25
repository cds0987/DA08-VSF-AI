// Helper THUẦN (không phụ thuộc Vue/lucide) cho NotificationCenter — tách ra để test độc
// lập bằng node:test. Phụ trách: thời gian tương đối, nhóm theo ngày, và phân loại sự kiện
// (key + nhãn + tone màu) cho .vue map sang icon. KHÔNG import '~/types' để chạy được dưới
// node --test (path alias không resolve ngoài Nuxt).

/** Tối thiểu cần để format/nhóm — khớp NotificationItem nhưng không lệ thuộc alias. */
export interface NotificationLike {
  created_at: string
  event?: string
}

const ABSOLUTE_FMT = new Intl.DateTimeFormat('vi-VN', {
  dateStyle: 'short',
  timeStyle: 'short',
})

/** Ngày + giờ tuyệt đối (dùng làm fallback và title hover). */
export function formatAbsolute(value: string): string {
  return ABSOLUTE_FMT.format(new Date(value))
}

const MINUTE = 60
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/**
 * Thời gian tương đối kiểu người đọc: "Vừa xong" / "5 phút trước" / "2 giờ trước" /
 * "3 ngày trước"; quá 7 ngày -> ngày tuyệt đối. `now` cho phép inject để test.
 */
export function formatRelativeTime(value: string, now: Date = new Date()): string {
  const then = new Date(value)
  const diffSec = Math.round((now.getTime() - then.getTime()) / 1000)

  // Mốc tương lai (lệch đồng hồ nhẹ) -> coi như vừa xong.
  if (diffSec < 45) return 'Vừa xong'
  if (diffSec < HOUR) return `${Math.floor(diffSec / MINUTE)} phút trước`
  if (diffSec < DAY) return `${Math.floor(diffSec / HOUR)} giờ trước`
  if (diffSec < 7 * DAY) return `${Math.floor(diffSec / DAY)} ngày trước`
  return formatAbsolute(value)
}

export type TimeGroupKey = 'today' | 'yesterday' | 'earlier'

export interface TimeGroup<T extends NotificationLike> {
  key: TimeGroupKey
  label: string
  items: T[]
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

/**
 * Nhóm thông báo theo ngày lịch: Hôm nay / Hôm qua / Trước đó. Giữ nguyên thứ tự items đầu
 * vào trong mỗi nhóm (store đã sort mới->cũ). Chỉ trả về nhóm có phần tử.
 */
export function groupByTime<T extends NotificationLike>(
  items: T[],
  now: Date = new Date(),
): TimeGroup<T>[] {
  const todayStart = startOfDay(now)
  const yesterdayStart = todayStart - DAY * 1000

  const buckets: Record<TimeGroupKey, T[]> = { today: [], yesterday: [], earlier: [] }
  for (const item of items) {
    const t = new Date(item.created_at).getTime()
    if (t >= todayStart) buckets.today.push(item)
    else if (t >= yesterdayStart) buckets.yesterday.push(item)
    else buckets.earlier.push(item)
  }

  const labels: Record<TimeGroupKey, string> = {
    today: 'Hôm nay',
    yesterday: 'Hôm qua',
    earlier: 'Trước đó',
  }
  const order: TimeGroupKey[] = ['today', 'yesterday', 'earlier']
  return order
    .filter((key) => buckets[key].length > 0)
    .map((key) => ({ key, label: labels[key], items: buckets[key] }))
}

/** Tone màu ngữ nghĩa cho từng loại — .vue map tone -> class light/dark + icon. */
export type NotificationTone = 'indigo' | 'emerald' | 'rose' | 'slate' | 'amber'

export interface NotificationKind {
  /** key ổn định để .vue chọn icon component. */
  key: 'doc_new' | 'leave_request_new' | 'leave_approved' | 'leave_rejected' | 'leave_cancelled' | 'generic'
  label: string
  tone: NotificationTone
}

const KIND_MAP: Record<string, NotificationKind> = {
  doc_new: { key: 'doc_new', label: 'Tài liệu mới', tone: 'indigo' },
  leave_request_new: { key: 'leave_request_new', label: 'Đơn nghỉ phép mới', tone: 'amber' },
  leave_approved: { key: 'leave_approved', label: 'Nghỉ phép được duyệt', tone: 'emerald' },
  leave_rejected: { key: 'leave_rejected', label: 'Nghỉ phép bị từ chối', tone: 'rose' },
  leave_cancelled: { key: 'leave_cancelled', label: 'Nghỉ phép đã huỷ', tone: 'slate' },
}

/** Phân loại sự kiện -> {key, label, tone}. Sự kiện lạ -> generic (chuông xám). */
export function notificationKind(event: string | undefined): NotificationKind {
  return (event && KIND_MAP[event]) || { key: 'generic', label: 'Thông báo', tone: 'slate' }
}
