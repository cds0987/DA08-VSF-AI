<script setup lang="ts">
import { 
  LayoutDashboard, 
  FileText, 
  Upload, 
  ShieldCheck, 
  Users, 
  PanelLeftOpen, 
  PanelLeftClose,
  Settings,
  LogOut,
  ChevronsUpDown
} from '@lucide/vue'
import { useSessionStore } from '~/stores/session'

const session = useSessionStore()
const router = useRouter()

const isCollapsed = ref(true)
const isAnimatingSidebar = ref(false)
const isHoveringLogo = ref(false)

const ADMIN_NAV = [
  { label: 'Dashboard', to: '/', icon: LayoutDashboard },
  { label: 'Documents', to: '/documents', icon: FileText },
  { label: 'Upload Center', to: '/upload', icon: Upload },
  { label: 'Audit Logs', to: '/audit', icon: ShieldCheck },
  { label: 'User Management', to: '/users', icon: Users },
]

const handleSignOut = () => {
  session.signOut()
  router.push('/login')
}

const sidebarWidth = computed(() => isCollapsed.value ? '64px' : '268px')
</script>

<template>
  <!-- Sidebar -->
  <aside
    class="flex shrink-0 flex-col relative z-50 transition-[width] duration-300 ease-in-out transform-gpu overflow-hidden h-full"
    :class="[
      isCollapsed ? 'w-16' : 'w-[268px]',
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
              @click="isCollapsed && (isCollapsed = false)"
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
                  :stroke-width="2.5"
                />
              </div>
            </button>
          </div>
          
          <div
            v-show="!isCollapsed"
            class="flex flex-col leading-tight whitespace-nowrap overflow-hidden transition-opacity duration-300"
          >
            <span class="text-[17px] font-extrabold tracking-tight text-[#0f172a] font-sans">
              FeatureMind
            </span>
          </div>
        </div>

        <button
          v-show="!isCollapsed"
          @click="isCollapsed = true"
          class="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900 bg-white border border-slate-200/50 shadow-sm cursor-pointer shrink-0 mr-4"
        >
          <PanelLeftClose
            class="h-5 w-5"
            :stroke-width="2.5"
          />
        </button>
      </div>
    </div>

    <!-- Navigation Area -->
    <div class="flex flex-col w-full overflow-hidden">
      <div
        class="flex flex-col w-full px-0 gap-2"
      >
          <!-- Admin Navigation -->
          <div
            class="flex flex-col gap-1 w-full"
          >
            <SideLink
              v-for="item in ADMIN_NAV"
              :key="item.to"
              :item="item"
              :is-collapsed="isCollapsed"
            />
          </div>
      </div>
    </div>

    <div class="flex-1" />

    <!-- Footer actions & user -->
    <div
      class="flex flex-col gap-1.5 shrink-0 w-full px-0 py-3"
    >
      <!-- Standalone Settings Button -->
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            class="flex items-center rounded-md cursor-pointer shrink-0 h-9 transition-all w-full text-slate-600 hover:bg-slate-100 hover:text-slate-900 px-0 justify-start"
          >
            <div class="flex h-9 w-[64px] items-center justify-center shrink-0">
              <Settings
                class="shrink-0 h-5 w-5"
              />
            </div>
            <span 
              class="text-[13px] font-semibold whitespace-nowrap transition-opacity duration-300"
              :class="isCollapsed ? 'opacity-0' : 'opacity-100'"
            >
              Settings
            </span>
          </button>
        </TooltipTrigger>
        <TooltipContent
          v-if="isCollapsed"
          side="right"
          class="bg-white/90 backdrop-blur-md border-slate-200 text-slate-900 shadow-md"
        >
          Settings
        </TooltipContent>
      </Tooltip>

      <!-- User Profile Dropdown -->
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            class="flex items-center rounded-md cursor-pointer shrink-0 h-12 transition-all px-0 w-full hover:bg-slate-100 justify-start"
          >
            <div class="flex h-12 w-[64px] items-center justify-center shrink-0">
              <div
                class="flex shrink-0 items-center justify-center rounded-full bg-blue-600 font-bold text-white border-2 border-blue-500 shadow-md transform-gpu transition-all hover:scale-105 h-9 w-9 text-xs"
              >
                {{ session.user?.initials }}
              </div>
            </div>
            <div
              class="min-w-0 flex-1 text-left flex flex-col justify-center transition-opacity duration-300"
              :class="isCollapsed ? 'opacity-0' : 'opacity-100'"
            >
              <div class="truncate text-sm font-semibold text-slate-900 leading-tight">
                {{ session.user?.name }}
              </div>
            </div>
            <ChevronsUpDown 
              class="h-4 w-4 text-slate-400 mr-2 shrink-0 transition-opacity duration-300" 
              :class="isCollapsed ? 'opacity-0' : 'opacity-100'"
            />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side="right"
          align="end"
          :side-offset="12"
          class="w-[180px] bg-white shadow-lg border-slate-100 text-slate-900 p-1.5"
        >
          <DropdownMenuLabel>My Account</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            class="flex items-center gap-2 rounded-md px-2 py-1.5 cursor-pointer focus:bg-slate-50 focus:text-slate-900 text-red-600 focus:text-red-700"
            @click="handleSignOut"
          >
            <LogOut class="h-4 w-4" />
            <span class="font-medium">Sign out</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  </aside>
</template>

<style scoped>
.toggle-btn {
  opacity: 0;
  visibility: hidden;
  transition: opacity 0.2s ease, visibility 0.2s ease, transform 0.2s ease;
  transition-delay: 0.2s, 0.2s, 0s;
}

.logo-container:hover .toggle-btn {
  opacity: 1;
  visibility: visible;
  transition-delay: 0s;
}
</style>


