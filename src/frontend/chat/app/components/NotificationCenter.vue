<script setup lang="ts">
import { Bell, Sparkles, WifiOff, X } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { useNotificationStore } from '~/stores/notifications'
import { useChatStore } from '~/stores/chat'
import type { NotificationItem } from '~/types'

defineProps<{
  isCollapsed: boolean
  disableTooltip?: boolean
}>()

const notifications = useNotificationStore()
const chat = useChatStore()
const router = useRouter()
const route = useRoute()
const isOpen = ref(false)
let lastFetchedAt = 0

function formatCreatedAt(value: string) {
  return new Intl.DateTimeFormat('vi-VN', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value))
}

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
  // Nếu đang ở /chat (new chat), inject trực tiếp; nếu không thì queue + navigate
  if (route.path === '/chat' && !route.params.id) {
    chat.injectProactiveMessage(docName, item.doc_id)
  } else {
    chat.queueProactiveMessage(docName, item.doc_id)
    await router.push('/chat')
  }
}

// Click X → mark read + xóa khỏi list
async function handleDismiss(event: MouseEvent, item: NotificationItem) {
  event.stopPropagation()
  if (!item.is_read) {
    await notifications.markAsRead(item.id).catch(() => {
      toast.error('Không thể đánh dấu thông báo đã đọc.')
    })
  }
  notifications.removeItem(item.id)
}
</script>

<template>
  <DropdownMenu v-model:open="isOpen">
    <Tooltip>
      <DropdownMenuTrigger as-child>
        <TooltipTrigger as-child>
          <button
            class="flex h-9 w-full shrink-0 cursor-pointer items-center justify-start rounded-md px-0 text-slate-600 transition-all hover:bg-slate-100 hover:text-slate-900 dark:text-muted-foreground dark:hover:bg-sidebar-accent dark:hover:text-sidebar-accent-foreground"
            aria-label="Thông báo"
          >
            <div class="relative flex h-9 w-[64px] shrink-0 items-center justify-center">
              <Bell class="h-5 w-5 shrink-0" />
              <span
                v-if="notifications.unreadCount > 0"
                class="absolute right-3 top-0.5 flex min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold leading-4 text-white"
              >
                {{ notifications.unreadCount > 99 ? '99+' : notifications.unreadCount }}
              </span>
            </div>
            <span
              class="whitespace-nowrap text-[13px] font-semibold transition-opacity duration-300"
              :class="isCollapsed ? 'opacity-0' : 'opacity-100'"
            >
              Thông báo
            </span>
          </button>
        </TooltipTrigger>
      </DropdownMenuTrigger>
      <TooltipContent
        v-if="isCollapsed && !disableTooltip"
        side="right"
        class="bg-slate-900 text-[11px] font-medium text-white dark:bg-slate-100 dark:text-slate-900 border-none shadow-md"
      >
        Thông báo
      </TooltipContent>
    </Tooltip>

      <DropdownMenuContent
        side="right"
        align="end"
        :side-offset="12"
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
          class="flex flex-col items-center gap-2 px-4 py-8 text-center text-sm text-slate-500 dark:text-muted-foreground"
        >
          <WifiOff class="h-5 w-5 text-slate-400 dark:text-muted-foreground" />
          Chưa có thông báo mới.
        </div>
        <div v-else class="notification-scrollbar max-h-[420px] overflow-y-auto p-1.5">
          <DropdownMenuItem
            v-for="item in notifications.items"
            :key="item.id"
            class="group items-start gap-3 cursor-pointer rounded-lg px-3 py-3 focus:bg-slate-50 dark:focus:bg-accent"
            @select="handleItemClick(item)"
          >
            <span
              class="mt-1.5 h-2 w-2 shrink-0 rounded-full"
              :class="item.is_read ? 'bg-slate-200 dark:bg-muted' : 'bg-blue-600'"
            />
            <span class="min-w-0 flex-1">
              <span
                class="block text-sm leading-5"
                :class="item.is_read ? 'font-normal text-slate-600 dark:text-muted-foreground' : 'font-semibold text-slate-900 dark:text-foreground'"
              >
                {{ item.message }}
              </span>
              <span class="mt-1 block text-xs text-slate-400 dark:text-muted-foreground">
                {{ formatCreatedAt(item.created_at) }}
              </span>
              <button
                v-if="!item.is_read && item.event === 'doc_new'"
                class="mt-1.5 inline-flex items-center gap-1 text-[11px] font-medium text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 transition-colors"
                @click="handleAskAI($event, item)"
              >
                <Sparkles class="h-3 w-3" /> Hỏi AI về tài liệu này
              </button>
            </span>
            <button
              class="mt-0.5 shrink-0 rounded p-0.5 text-slate-300 opacity-0 transition-opacity hover:bg-slate-100 hover:text-slate-600 group-hover:opacity-100 dark:text-muted-foreground/50 dark:hover:bg-white/5 dark:hover:text-muted-foreground"
              @click="handleDismiss($event, item)"
            >
              <X class="h-3.5 w-3.5" />
            </button>
          </DropdownMenuItem>
        </div>
      </DropdownMenuContent>
  </DropdownMenu>
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
