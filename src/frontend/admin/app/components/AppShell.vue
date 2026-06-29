<script setup lang="ts">
import {
  LayoutDashboard,
  FileText,
  Upload,
  ShieldCheck,
  Briefcase,
  PanelLeftOpen,
  PanelLeftClose,
  Settings,
  LogOut,
  ChevronsUpDown
} from '@lucide/vue'
import { useSessionStore } from '~/stores/session'

const session = useSessionStore()

const isCollapsed = ref(true)
const isHoveringLogo = ref(false)
// Settings mở từ dropdown account (DeepSeek-style) -> dialog điều khiển bằng state.
const settingsOpen = ref(false)

// Chặn tooltip tự mở khi đổi width sidebar (đồng bộ chat — xem docs/sidebar-tooltip-phantom-hover-fix.md).
// reka-ui mở tooltip trên `pointermove`; layout shift khi đổi width khiến Chrome bắn pointermove
// GIẢ tại đúng toạ độ con trỏ -> tooltip bật dù user không di chuột. Phải phân biệt move GIẢ
// (trùng toạ độ) vs move THẬT (lệch > 3px) để gỡ chặn đúng lúc.
const suppressTooltips = ref(false)
let suppressBaseline: { x: number, y: number } | null = null
let suppressMoveHandler: ((e: PointerEvent) => void) | null = null

function removeSuppressListener() {
  if (suppressMoveHandler && typeof document !== 'undefined') {
    document.removeEventListener('pointermove', suppressMoveHandler)
  }
  suppressMoveHandler = null
  suppressBaseline = null
}

function clearSuppressOnRealMove() {
  if (typeof document === 'undefined') return
  removeSuppressListener() // tránh chồng listener nếu toggle liên tiếp
  suppressMoveHandler = (e: PointerEvent) => {
    // pointermove ĐẦU TIÊN sau collapse thường là move GIẢ (layout shift) -> làm mốc, chưa gỡ.
    if (!suppressBaseline) {
      suppressBaseline = { x: e.clientX, y: e.clientY }
      return
    }
    // Chỉ gỡ chặn khi con trỏ THỰC SỰ dịch > 3px (move giả luôn trùng toạ độ mốc).
    if (Math.abs(e.clientX - suppressBaseline.x) + Math.abs(e.clientY - suppressBaseline.y) > 3) {
      suppressTooltips.value = false
      removeSuppressListener()
    }
  }
  document.addEventListener('pointermove', suppressMoveHandler)
}

function setSidebarCollapsed(value: boolean) {
  suppressTooltips.value = true
  isCollapsed.value = value
  clearSuppressOnRealMove()
}

onUnmounted(removeSuppressListener)

const ADMIN_NAV = [
  { label: 'Dashboard', to: '/', icon: LayoutDashboard },
  { label: 'Documents', to: '/documents', icon: FileText },
  { label: 'Upload Center', to: '/upload', icon: Upload },
  { label: 'Audit Logs', to: '/audit', icon: ShieldCheck },
  { label: 'Employee Management', to: '/employees', icon: Briefcase },
]

const handleSignOut = () => {
  // session.signOut() -> authService.logout() đã tự điều hướng tới /login (hard redirect)
  // sau khi clear cookie; router.push thừa ở đây gây double navigation.
  session.signOut()
}

// Hiện full email (không che) — tài khoản của chính người dùng trong app nội bộ (khớp chat).
const userEmail = computed(() => session.user?.email ?? '')

const userInitials = computed(() => {
  if (session.user?.initials) return session.user.initials
  return (session.user?.email ?? '').slice(0, 2).toUpperCase()
})
</script>

<template>
  <!-- Sidebar -->
  <aside
    class="flex shrink-0 flex-col relative z-50 h-full overflow-hidden text-sidebar-foreground transition-[width,background-color,border-color] duration-300 ease-in-out transform-gpu"
    :class="[
      isCollapsed
        ? 'w-16 bg-transparent border-r border-transparent'
        : 'w-[268px] bg-sidebar border-r border-sidebar-border',
    ]"
    style="display: flex !important; isolation: isolate; contain: layout style paint; will-change: width, transform;"
  >
    <!-- Brand & Toggle -->
    <div
      class="flex h-20 items-center shrink-0 w-full mb-4 px-0"
    >
      <div
        class="flex items-center w-full justify-between"
      >
        <div class="flex items-center">
          <div class="flex h-20 w-[64px] items-center justify-center shrink-0">
            <button
              @click="isCollapsed && setSidebarCollapsed(false)"
              @mouseenter="isHoveringLogo = true"
              @mouseleave="isHoveringLogo = false"
              class="relative flex items-center justify-center shrink-0 group outline-none cursor-pointer h-11 w-11"
              style="transform: translate3d(0, 0, 0); backface-visibility: hidden; will-change: transform; perspective: 1000px;"
            >
              <!-- Red Halo/Glow Effect -->
              <div
                class="absolute inset-0 rounded-full bg-red-500/10"
                style="will-change: transform, opacity; transform: translate3d(0, 0, 0); backface-visibility: hidden; isolation: isolate;"
              />

              <div
                class="relative z-10 flex items-center justify-center h-11 w-11 shrink-0"
                :class="isCollapsed && isHoveringLogo ? 'opacity-0' : 'opacity-100'"
                style="transform: translate3d(0, 0, 0); backface-visibility: hidden;"
              >
                <OctopusLogo
                  :size="32"
                  class="saturate-100"
                />
              </div>

              <div
                v-if="isCollapsed"
                class="absolute inset-0 z-20 flex items-center justify-center rounded-full bg-red-500/10 border border-red-500/20 text-[#0f172a]"
                :class="isHoveringLogo ? 'opacity-100' : 'opacity-0 pointer-events-none'"
              >
                <PanelLeftOpen
                  class="h-5 w-5 text-red-600"
                  :stroke-width="2"
                />
              </div>
            </button>
          </div>

          <div
            class="flex flex-col leading-tight whitespace-nowrap overflow-hidden transition-opacity duration-300"
            :class="isCollapsed ? 'opacity-0 pointer-events-none' : 'opacity-100'"
          >
            <span class="text-[17px] font-extrabold tracking-tight text-[#0f172a] dark:text-sidebar-foreground font-sans">
              FeatureMind
            </span>
          </div>
        </div>

        <button
          @click="setSidebarCollapsed(true)"
          class="rounded-md p-1.5 text-slate-900 dark:text-white hover:bg-slate-100 dark:hover:bg-sidebar-accent hover:text-slate-900 dark:hover:text-sidebar-accent-foreground bg-white dark:bg-card border border-slate-200/50 dark:border-sidebar-border shadow-sm cursor-pointer shrink-0 mr-4 transition-opacity duration-300"
          :class="isCollapsed ? 'opacity-0 pointer-events-none' : 'opacity-100'"
        >
          <PanelLeftClose
            class="h-5 w-5"
            :stroke-width="2"
          />
        </button>
      </div>
    </div>

    <!-- Navigation Area -->
    <div class="flex flex-col w-full flex-1 min-h-0 overflow-hidden">
      <div
        class="flex flex-col w-full px-0 gap-2"
      >
        <!-- Nhóm nav: khi thu gọn -> khung bo tròn "lơ lửng" bao các icon (DeepSeek-style, khớp chat) -->
        <div
          class="flex flex-col"
          :class="isCollapsed
            ? 'mx-auto w-12 gap-1 rounded-2xl border border-slate-200/70 bg-white/80 p-1 shadow-sm dark:border-white/10 dark:bg-white/5'
            : 'w-full gap-2'"
        >
          <SideLink
            v-for="item in ADMIN_NAV"
            :key="item.to"
            :item="item"
            :is-collapsed="isCollapsed"
            :disable-tooltip="suppressTooltips"
          />
        </div>
      </div>
    </div>

    <!-- Footer actions & user -->
    <div
      class="flex flex-col gap-1.5 shrink-0 w-full px-0 py-3"
    >
      <!-- Settings dialog — KHÔNG trigger, mở từ dropdown account (state-controlled) -->
      <Dialog v-model:open="settingsOpen">
        <SettingsDialog />
      </Dialog>

      <!-- User Profile Dropdown (account) — chứa email, Settings, Sign out. Ẩn khi thu gọn. -->
      <div v-show="!isCollapsed">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              class="flex items-center rounded-md cursor-pointer shrink-0 h-12 transition-all px-0 w-full hover:bg-slate-100 dark:hover:bg-sidebar-accent justify-start"
            >
              <div class="flex h-12 w-[64px] items-center justify-center shrink-0">
                <div
                  class="flex shrink-0 items-center justify-center rounded-full bg-blue-600 font-bold text-white border-2 border-blue-500 shadow-md transform-gpu transition-all hover:scale-105 h-9 w-9 text-xs"
                >
                  {{ userInitials }}
                </div>
              </div>
              <div
                class="min-w-0 flex-1 text-left flex flex-col justify-center transition-opacity duration-300"
                :class="isCollapsed ? 'opacity-0' : 'opacity-100'"
              >
                <div class="truncate text-sm font-semibold text-slate-900 dark:text-sidebar-foreground leading-tight">
                  {{ userEmail }}
                </div>
              </div>
              <ChevronsUpDown
                class="h-4 w-4 text-slate-400 dark:text-muted-foreground/70 mr-2 shrink-0 transition-opacity duration-300"
                :class="isCollapsed ? 'opacity-0' : 'opacity-100'"
              />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            side="top"
            align="start"
            :side-offset="8"
            class="w-[240px] bg-white dark:bg-popover shadow-lg border-slate-100 dark:border-sidebar-border text-slate-900 dark:text-sidebar-foreground p-1.5"
          >
            <!-- Header: avatar + email -->
            <DropdownMenuLabel class="flex items-center gap-2.5 px-2 py-1.5">
              <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[11px] font-bold text-white">
                {{ userInitials }}
              </div>
              <span class="min-w-0 flex-1 truncate text-[13px] font-semibold text-slate-900 dark:text-sidebar-foreground">{{ userEmail }}</span>
            </DropdownMenuLabel>
            <DropdownMenuSeparator class="bg-slate-100 dark:bg-sidebar-accent" />
            <DropdownMenuItem
              class="flex items-center gap-2 rounded-md px-2 py-1.5 cursor-pointer focus:bg-slate-50 dark:focus:bg-sidebar-accent focus:text-slate-900 dark:focus:text-sidebar-accent-foreground"
              @select="settingsOpen = true"
            >
              <Settings class="h-4 w-4" />
              <span class="font-medium">Settings</span>
            </DropdownMenuItem>
            <DropdownMenuSeparator class="bg-slate-100 dark:bg-sidebar-accent" />
            <DropdownMenuItem
              class="flex items-center gap-2 rounded-md px-2 py-1.5 cursor-pointer focus:bg-slate-50 dark:focus:bg-sidebar-accent focus:text-slate-900 dark:focus:text-sidebar-accent-foreground text-red-600 focus:text-red-700"
              @click="handleSignOut"
            >
              <LogOut class="h-4 w-4" />
              <span class="font-medium">Sign out</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  </aside>
</template>
