<script setup lang="ts">
import {
  Ban,
  Bell,
  BellOff,
  CalendarClock,
  CheckCircle2,
  FileText,
  Sparkles,
  X,
  XCircle,
} from '@lucide/vue'
import type { Component } from 'vue'
import { toast } from 'vue-sonner'
import { useNotificationStore } from '~/stores/notifications'
import { useChatStore } from '~/stores/chat'
import { useQueryService } from '~/lib/api/queryService'
import {
  formatAbsolute,
  formatRelativeTime,
  groupByTime,
  notificationKind,
  type NotificationTone,
} from '~/lib/notificationFormat'
import type { NotificationItem } from '~/types'

// Chuông sống trong AppTopBar (góc trên-phải khu main) -> badge luôn thấy dù sidebar đóng/mở.
const notifications = useNotificationStore()
const chat = useChatStore()
const queryService = useQueryService()
const isOpen = ref(false)
let lastFetchedAt = 0

// Map tone ngữ nghĩa -> class nền/màu icon (light + dark). Tách khỏi helper vì phụ thuộc UI.
const TONE_CLASS: Record<NotificationTone, string> = {
  indigo: 'bg-indigo-50 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-400',
  emerald: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-400',
  rose: 'bg-rose-50 text-rose-600 dark:bg-rose-500/15 dark:text-rose-400',
  amber: 'bg-amber-50 text-amber-600 dark:bg-amber-500/15 dark:text-amber-400',
  slate: 'bg-slate-100 text-slate-500 dark:bg-white/10 dark:text-muted-foreground',
}

const KIND_ICON: Record<string, Component> = {
  doc_new: FileText,
  leave_request_new: CalendarClock,
  leave_approved: CheckCircle2,
  leave_rejected: XCircle,
  leave_cancelled: Ban,
  generic: Bell,
}

interface DecoratedItem {
  item: NotificationItem
  icon: Component
  toneClass: string
}

// Gom item theo Hôm nay / Hôm qua / Trước đó + đính sẵn icon/tone MỘT lần (tránh tính lại
// mỗi render). Chỉ chạy lại khi items đổi.
const groups = computed(() =>
  groupByTime(notifications.items).map((group) => ({
    key: group.key,
    label: group.label,
    items: group.items.map((item): DecoratedItem => {
      const kind = notificationKind(item.event)
      return { item, icon: KIND_ICON[kind.key] ?? Bell, toneClass: TONE_CLASS[kind.tone] }
    }),
  })),
)

function extractDocName(message: string): string {
  return message.replace('Có tài liệu mới: ', '').trim()
}

async function handleOpen(open: boolean) {
  if (!open) return
  const now = Date.now()
  if (now - lastFetchedAt < 30_000) return  // throttle: không re-fetch trong 30s
  lastFetchedAt = now
  await Promise.all([
    notifications.fetchHistory(),
    notifications.fetchUnreadCount(),
  ]).catch(() => {
    toast.error('Không thể tải danh sách thông báo.')
  })
}

watch(isOpen, (open) => { if (open) void handleOpen(open) })

// Click item body → chỉ mark read, dropdown tự đóng qua @select
async function handleItemClick(item: NotificationItem) {
  if (!item.is_read) {
    await notifications.markAsRead(item.id).catch(() => {})
  }
}

// Click "Hỏi AI" button → đóng dropdown + inject AI + navigate
async function handleAskAI(event: MouseEvent, item: NotificationItem) {
  event.stopPropagation()
  isOpen.value = false
  if (!item.is_read) {
    await notifications.markAsRead(item.id).catch(() => {})
  }
  const docName = extractDocName(item.message)
  // Chèn gợi ý vào HỘI THOẠI HIỆN TẠI (cả /chat lẫn /chat/:id) — KHÔNG mở new chat.
  // injectProactiveMessage tự bump tick -> page cuộn tới card.
  chat.injectProactiveMessage(docName, item.doc_id)
}

// Click X → xóa hẳn khỏi DB + list (không refresh lại nữa)
async function handleDismiss(event: MouseEvent, item: NotificationItem) {
  event.stopPropagation()
  notifications.removeItem(item.id)   // optimistic: ẩn ngay
  await queryService.deleteNotification(item.id).catch(() => {
    // best-effort: nếu lỗi thì để lại (sẽ thấy lại khi refresh)
  })
}
</script>

<template>
  <Tooltip :ignore-non-keyboard-focus="true">
    <TooltipTrigger as-child>
      <div>
        <DropdownMenu v-model:open="isOpen">
          <DropdownMenuTrigger as-child>
            <button
              class="relative flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full border border-slate-200/70 bg-white/70 text-slate-600 transition-colors hover:bg-white hover:text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 data-[state=open]:bg-slate-100 data-[state=open]:text-slate-900 dark:border-white/10 dark:bg-white/5 dark:text-muted-foreground dark:hover:bg-white/10 dark:hover:text-foreground dark:data-[state=open]:bg-white/10 dark:data-[state=open]:text-foreground"
              aria-label="Thông báo"
            >
              <Bell class="h-[18px] w-[18px] shrink-0" />
              <span
                v-if="notifications.unreadCount > 0"
                aria-live="polite"
                class="absolute -right-1 -top-1 flex min-w-[16px] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold leading-4 text-white ring-2 ring-background"
              >
                {{ notifications.unreadCount > 99 ? '99+' : notifications.unreadCount }}
              </span>
            </button>
          </DropdownMenuTrigger>

          <DropdownMenuContent
            side="bottom"
            align="end"
            :side-offset="8"
            class="w-[360px] border-slate-200 dark:border-border bg-white dark:bg-popover p-0 text-slate-900 dark:text-popover-foreground shadow-xl"
          >
            <div class="flex items-center justify-between border-b border-slate-100 dark:border-border px-4 py-3">
              <div>
                <p class="text-sm font-bold">Thông báo</p>
                <p class="text-xs text-slate-500 dark:text-muted-foreground">
                  {{ notifications.unreadCount }} chưa đọc
                </p>
              </div>
              <span
                class="flex items-center gap-1 text-[11px]"
                :class="notifications.isConnected ? 'text-emerald-600' : 'text-amber-600'"
              >
                <span
                  class="h-1.5 w-1.5 rounded-full"
                  :class="notifications.isConnected ? 'bg-emerald-500' : 'bg-amber-500'"
                />
                {{ notifications.isConnected ? 'Realtime' : 'Đang kết nối lại' }}
              </span>
            </div>

            <div v-if="notifications.isLoading" class="px-4 py-8 text-center text-sm text-slate-500 dark:text-muted-foreground">
              Đang tải thông báo...
            </div>
            <div
              v-else-if="notifications.items.length === 0"
              class="flex flex-col items-center gap-2 px-4 py-10 text-center text-sm text-slate-500 dark:text-muted-foreground"
            >
              <BellOff class="h-6 w-6 text-slate-400 dark:text-muted-foreground" />
              Chưa có thông báo mới.
            </div>
            <div v-else class="notification-scrollbar max-h-[min(420px,70vh)] overflow-y-auto p-1.5">
              <div v-for="group in groups" :key="group.key">
                <p
                  class="sticky top-0 z-10 bg-white/90 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400 backdrop-blur-sm dark:bg-popover/90 dark:text-muted-foreground"
                >
                  {{ group.label }}
                </p>
                <DropdownMenuItem
                  v-for="entry in group.items"
                  :key="entry.item.id"
                  class="group items-start gap-3 cursor-pointer rounded-lg px-2.5 py-2.5 focus:bg-slate-50 dark:focus:bg-accent"
                  @select="handleItemClick(entry.item)"
                >
                  <span class="relative mt-0.5 shrink-0">
                    <span
                      class="flex h-8 w-8 items-center justify-center rounded-lg"
                      :class="entry.toneClass"
                    >
                      <component :is="entry.icon" class="h-4 w-4" />
                    </span>
                    <span
                      v-if="!entry.item.is_read"
                      class="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-blue-600 ring-2 ring-white dark:ring-popover"
                      aria-label="Chưa đọc"
                    />
                  </span>
                  <span class="min-w-0 flex-1">
                    <span
                      class="block text-sm leading-5 line-clamp-2"
                      :class="entry.item.is_read ? 'font-normal text-slate-600 dark:text-muted-foreground' : 'font-semibold text-slate-900 dark:text-foreground'"
                    >
                      {{ entry.item.message }}
                    </span>
                    <span
                      class="mt-0.5 block text-xs text-slate-400 dark:text-muted-foreground"
                      :title="formatAbsolute(entry.item.created_at)"
                    >
                      {{ formatRelativeTime(entry.item.created_at) }}
                    </span>
                    <button
                      v-if="!entry.item.is_read && entry.item.event === 'doc_new'"
                      class="mt-1.5 inline-flex items-center gap-1 rounded text-[11px] font-medium text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-indigo-500 transition-colors"
                      @click="handleAskAI($event, entry.item)"
                    >
                      <Sparkles class="h-3 w-3" /> Hỏi AI về tài liệu này
                    </button>
                  </span>
                  <button
                    class="mt-0.5 shrink-0 rounded p-1 text-slate-300 opacity-0 transition-opacity hover:bg-slate-100 hover:text-slate-600 focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-blue-500 group-hover:opacity-100 dark:text-muted-foreground/50 dark:hover:bg-white/5 dark:hover:text-muted-foreground"
                    aria-label="Bỏ qua thông báo"
                    @click="handleDismiss($event, entry.item)"
                  >
                    <X class="h-3.5 w-3.5" />
                  </button>
                </DropdownMenuItem>
              </div>
            </div>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </TooltipTrigger>
    <TooltipContent
      side="bottom"
      class="bg-slate-900 text-[11px] font-medium text-white dark:bg-slate-100 dark:text-slate-900 border-none shadow-md"
    >
      Thông báo
    </TooltipContent>
  </Tooltip>
</template>

<style scoped>
:global(.dark .notification-scrollbar) {
  scrollbar-width: thin;
  scrollbar-color: rgb(255 255 255 / 18%) #1b1b1f;
}

:global(.dark .notification-scrollbar::-webkit-scrollbar) {
  width: 6px;
}

:global(.dark .notification-scrollbar::-webkit-scrollbar-track) {
  background: #1b1b1f;
  border-radius: 9999px;
}

:global(.dark .notification-scrollbar::-webkit-scrollbar-thumb) {
  background-color: rgb(255 255 255 / 18%);
  border: 1px solid #1b1b1f;
  border-radius: 9999px;
}

:global(.dark .notification-scrollbar::-webkit-scrollbar-thumb:hover) {
  background-color: rgb(255 255 255 / 28%);
}
</style>
