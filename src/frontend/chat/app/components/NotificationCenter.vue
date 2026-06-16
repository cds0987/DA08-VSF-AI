<script setup lang="ts">
import { Bell, Check, WifiOff } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { useNotificationStore } from '~/stores/notifications'
import type { NotificationItem } from '~/types'

defineProps<{
  isCollapsed: boolean
}>()

const notifications = useNotificationStore()

function formatCreatedAt(value: string) {
  return new Intl.DateTimeFormat('vi-VN', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value))
}

async function handleOpen(open: boolean) {
  if (!open) return
  await Promise.all([
    notifications.fetchHistory(),
    notifications.fetchUnreadCount(),
  ]).catch(() => {
    toast.error('Không thể tải danh sách thông báo.')
  })
}

async function handleNotificationClick(item: NotificationItem) {
  if (item.is_read) return
  try {
    await notifications.markAsRead(item.id)
  } catch {
    toast.error('Không thể đánh dấu thông báo đã đọc.')
  }
}
</script>

<template>
  <Tooltip>
    <DropdownMenu @update:open="handleOpen">
      <TooltipTrigger as-child>
        <DropdownMenuTrigger as-child>
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
        </DropdownMenuTrigger>
      </TooltipTrigger>

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
            class="items-start gap-3 cursor-pointer rounded-lg px-3 py-3 focus:bg-slate-50 dark:focus:bg-accent"
            @select="handleNotificationClick(item)"
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
            </span>
            <Check v-if="item.is_read" class="mt-0.5 h-4 w-4 shrink-0 text-slate-300 dark:text-muted-foreground/50" />
          </DropdownMenuItem>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>

    <TooltipContent
      v-if="isCollapsed"
      side="right"
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
