<script setup lang="ts">
import {
  SquarePlus,
  Search,
  PanelLeftOpen,
  PanelLeftClose,
  Settings,
  LogOut,
  ChevronsUpDown,
  CalendarCheck
} from '@lucide/vue'
import { useSessionStore } from '~/stores/session'
import { useChatStore } from '~/stores/chat'
import { cn } from '~/lib/utils'

const session = useSessionStore()
const chat = useChatStore()
const router = useRouter()
const route = useRoute()

const isCollapsed = ref(true)
const isAnimatingSidebar = ref(false)
const isHoveringLogo = ref(false)
// Settings giờ mở từ dropdown account (DeepSeek-style) -> dialog điều khiển bằng state.
const settingsOpen = ref(false)

function setSidebarCollapsed(value: boolean) {
  // Trong lúc transition width (300ms), các icon trượt dưới con trỏ đứng yên
  // -> browser bắn pointerenter giả -> tooltip mở. Set isAnimatingSidebar để
  // truyền :disabled cho Tooltip, vô hiệu hóa hoàn toàn trong thời gian này.
  isAnimatingSidebar.value = true
  isCollapsed.value = value
  setTimeout(() => { isAnimatingSidebar.value = false }, 350)
}
const searchQuery = ref('')
const searchInputRef = ref<HTMLInputElement | null>(null)

const handleNewChat = () => {
  chat.clear()
  if (route.path !== '/chat') {
    router.push('/chat')
  }
}

const handleSearchClick = () => {
  if (isCollapsed.value) {
    isCollapsed.value = false
    setTimeout(() => searchInputRef.value?.focus(), 200)
  } else {
    searchInputRef.value?.focus()
  }
}

const handleSignOut = () => {
  // Xóa currentConversationId trước khi redirect: sau login lại sẽ hiện chat mới
  // thay vì nhảy về session cũ (giống ChatGPT/Gemini).
  chat.clear()
  session.signOut()
}

const sidebarWidth = computed(() => isCollapsed.value ? '64px' : '268px')

const maskedEmail = computed(() => {
  const email = session.user?.email
  if (!email) return ''
  const [local, domain] = email.split('@')
  if (!domain) return email
  return `${local.slice(0, 3)}*****@${domain}`
})

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
      isAnimatingSidebar ? 'pointer-events-none' : '',
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
          class="rounded-md p-1.5 text-slate-500 dark:text-muted-foreground hover:bg-slate-100 dark:hover:bg-sidebar-accent hover:text-slate-900 dark:hover:text-sidebar-accent-foreground bg-white dark:bg-chat-input border border-slate-200/50 dark:border-sidebar-border shadow-sm cursor-pointer shrink-0 mr-4 transition-opacity duration-300"
          :class="isCollapsed ? 'opacity-0 pointer-events-none' : 'opacity-100'"
        >
          <PanelLeftClose
            class="h-5 w-5"
            :stroke-width="2"
          />
        </button>
      </div>
    </div>

    <!-- Navigation Area — flex-1 + min-h-0 cho phép ChatHistory cuộn bên trong -->
    <div class="flex flex-col w-full flex-1 min-h-0 overflow-hidden">
      <div
        class="flex flex-col w-full h-full px-0 gap-2"
      >
        <!-- App chat KHÔNG có trang admin (admin là app riêng) -> luôn hiển thị nav chat,
             kể cả account role admin. Tránh /leave-approvals lật shell sang nav admin. -->
        <div class="w-full flex flex-col gap-2 flex-1 min-h-0">
          <!-- Nhóm nav: khi thu gọn -> khung bo tròn "lơ lửng" bao 3 icon (DeepSeek-style) -->
          <div
            class="flex flex-col"
            :class="isCollapsed
              ? 'mx-auto w-12 gap-1 rounded-2xl border border-slate-200/70 bg-white/80 p-1 shadow-sm dark:border-white/10 dark:bg-white/5'
              : 'w-full gap-2'"
          >
            <!-- New Chat Section -->
            <div class="w-full">
              <Tooltip :disabled="isAnimatingSidebar" :ignore-non-keyboard-focus="true">
                <TooltipTrigger asChild>
                  <button
                    @click="handleNewChat"
                    class="group flex items-center rounded-lg overflow-hidden cursor-pointer shrink-0 h-9 transition-all w-full bg-transparent px-0 text-sm font-semibold text-slate-900 dark:text-sidebar-foreground hover:bg-slate-100 dark:hover:bg-sidebar-accent focus-visible:ring-0 outline-none"
                  >
                    <div class="flex h-9 items-center justify-center shrink-0" :class="isCollapsed ? 'w-full' : 'w-[64px]'">
                      <SquarePlus
                        class="h-5 w-5 shrink-0"
                        :class="!isCollapsed ? 'text-blue-600 dark:text-blue-400' : 'text-slate-500 dark:text-muted-foreground'"
                      />
                    </div>
                    <span
                      class="whitespace-nowrap transition-opacity duration-300"
                      :class="isCollapsed ? 'opacity-0' : 'opacity-100'"
                    >
                      New Chat
                    </span>
                  </button>
                </TooltipTrigger>
                <TooltipContent
                  v-if="isCollapsed"
                  side="right"
                  class="bg-slate-900 text-[11px] font-medium text-white dark:bg-slate-100 dark:text-slate-900 border-none shadow-md"
                >
                  New Chat
                </TooltipContent>
              </Tooltip>
            </div>

            <!-- Đơn nghỉ phép: trang duyệt đơn (sếp thấy hàng đợi; nhân viên thấy rỗng) -->
            <SideLink
              :item="{ label: 'Đơn nghỉ phép', to: '/leave-approvals', icon: CalendarCheck }"
              :is-collapsed="isCollapsed"
              :disable-tooltip="isAnimatingSidebar"
            />

            <!-- Search -->
            <div class="w-full">
              <Tooltip :disabled="isAnimatingSidebar" :ignore-non-keyboard-focus="true">
                <TooltipTrigger asChild>
                  <div
                    :role="isCollapsed ? 'button' : undefined"
                    :tabindex="isCollapsed ? 0 : -1"
                    class="relative group flex items-center overflow-hidden rounded-lg shrink-0 h-9 transition-all w-full bg-transparent shadow-none cursor-pointer hover:bg-slate-100 dark:hover:bg-sidebar-accent"
                    @click="isCollapsed && handleSearchClick()"
                  >
                    <div class="flex h-9 items-center justify-center shrink-0" :class="isCollapsed ? 'w-full' : 'w-[64px]'">
                      <Search
                        class="h-5 w-5 shrink-0 z-10"
                        :class="isCollapsed
                          ? 'text-slate-500 dark:text-muted-foreground'
                          : 'text-slate-400 dark:text-muted-foreground/70 group-focus-within:text-blue-600 dark:group-focus-within:text-blue-400'"
                      />
                    </div>
                    <input
                      ref="searchInputRef"
                      type="text"
                      placeholder="Search messages..."
                      v-model="searchQuery"
                      class="w-full bg-transparent py-2 pr-3 text-sm outline-none focus-visible:ring-0 shadow-none text-slate-900 dark:text-sidebar-foreground placeholder:text-slate-400 dark:placeholder:text-chat-placeholder whitespace-nowrap transition-opacity duration-300"
                      :class="isCollapsed ? 'opacity-0 pointer-events-none' : 'opacity-100'"
                      :disabled="isCollapsed"
                    />
                  </div>
                </TooltipTrigger>
                <TooltipContent
                  v-if="isCollapsed"
                  side="right"
                  class="bg-slate-900 text-[11px] font-medium text-white dark:bg-slate-100 dark:text-slate-900 border-none shadow-md"
                >
                  Search messages
                </TooltipContent>
              </Tooltip>
            </div>
          </div>
          <!-- /Nhóm nav khung bo tròn -->

          <ChatHistory :is-collapsed="isCollapsed" :query="searchQuery" class="w-full flex flex-col flex-1 min-h-0" />
          </div>
      </div>
    </div>

    <!-- Footer actions & user -->
    <div
      class="flex flex-col gap-1.5 shrink-0 w-full px-0 py-3"
    >
      <!-- Thông báo: ẩn khi thu gọn (chỉ hiện khi sidebar mở) -->
      <div v-show="!isCollapsed">
        <NotificationCenter
          :is-collapsed="isCollapsed"
          :disable-tooltip="isAnimatingSidebar"
        />
      </div>

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
                {{ maskedEmail }}
              </div>
            </div>
            <ChevronsUpDown
              class="h-4 w-4 text-slate-400 dark:text-muted-foreground/70 mr-2 shrink-0 transition-opacity duration-300"
              :class="isCollapsed ? 'opacity-0' : 'opacity-100'"
            />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side="right"
          align="end"
          :side-offset="12"
          class="w-[220px] bg-white dark:bg-chat-input shadow-lg border-slate-100 dark:border-sidebar-border text-slate-900 dark:text-sidebar-foreground p-1.5"
        >
          <!-- Header: avatar + email (hữu ích khi sidebar thu gọn) -->
          <DropdownMenuLabel class="flex items-center gap-2.5 px-2 py-1.5">
            <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[11px] font-bold text-white">
              {{ userInitials }}
            </div>
            <span class="min-w-0 flex-1 truncate text-[13px] font-semibold text-slate-900 dark:text-sidebar-foreground">{{ maskedEmail }}</span>
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
