<script setup lang="ts">
import { Loader2, Trash2, Edit2, MoreHorizontal } from '@lucide/vue'
import { ref, nextTick } from 'vue'
import { onClickOutside } from '@vueuse/core'
import { toast } from 'vue-sonner'
import { cn } from '~/lib/utils'
import { useChatStore } from '~/stores/chat'

defineProps<{
  isCollapsed: boolean
  query?: string
}>()

const chat = useChatStore()

// Modal state
const isRenameModalOpen = ref(false)
const renameTargetId = ref<string | null>(null)
const renameTargetTitle = ref('')
const renameInputRef = ref<HTMLInputElement | null>(null)

const isDeleteModalOpen = ref(false)
const deleteTargetId = ref<string | null>(null)

// Dropdown menu state
const activeMenuId = ref<string | null>(null)
const activeDropdownRef = ref<HTMLElement | null>(null)
const moreButtonRefs = ref<Record<string, HTMLButtonElement | null>>({})

function setMoreButtonRef(el: any, id: string) {
  if (el) {
    moreButtonRefs.value[id] = el
  }
}

// Correctly handle click outside
onClickOutside(activeDropdownRef, (event) => {
  if (!activeMenuId.value) return
  
  // Check if the click was on the toggle button for the currently active menu
  const toggleButton = moreButtonRefs.value[activeMenuId.value]
  const isClickOnToggle = toggleButton && (toggleButton === event.target || toggleButton.contains(event.target as Node))
  
  if (!isClickOnToggle) {
    activeMenuId.value = null
  }
})

function toggleMenu(id: string) {
  activeMenuId.value = activeMenuId.value === id ? null : id
}

function openRenameModal(id: string, currentTitle: string) {
  activeMenuId.value = null
  renameTargetId.value = id
  renameTargetTitle.value = currentTitle
  isRenameModalOpen.value = true
  nextTick(() => {
    renameInputRef.value?.focus()
  })
}

function closeRenameModal() {
  isRenameModalOpen.value = false
  renameTargetId.value = null
  renameTargetTitle.value = ''
}

async function handleRename() {
  if (!renameTargetId.value) return
  const title = renameTargetTitle.value.trim()
  
  if (!title || title === chat.conversations.find((c) => c.id === renameTargetId.value)?.title) {
    closeRenameModal()
    return
  }

  try {
    await chat.renameConversation(renameTargetId.value, title)
    closeRenameModal()
    toast.success('Đã đổi tên cuộc trò chuyện.')
  } catch (error) {
    toast.error('Không thể đổi tên cuộc trò chuyện.')
  }
}

function confirmDelete(id: string) {
  activeMenuId.value = null
  deleteTargetId.value = id
  isDeleteModalOpen.value = true
}

function closeDeleteModal() {
  isDeleteModalOpen.value = false
  deleteTargetId.value = null
}

async function handleDelete() {
  if (!deleteTargetId.value) return
  
  try {
    chat.deleteConversation(deleteTargetId.value)
    toast.success('Đã xóa cuộc trò chuyện.')
    closeDeleteModal()
  } catch {
    toast.error('Không thể xóa cuộc trò chuyện.')
  }
}

async function clearHistory() {
  if (!window.confirm('Bạn có chắc muốn xóa toàn bộ lịch sử trò chuyện?')) return

  try {
    await chat.clearHistory()
    toast.success('Đã xóa lịch sử trò chuyện.')
  } catch {
    toast.error('Không thể xóa lịch sử trên server. Lịch sử hiện tại được giữ nguyên.')
  }
}

</script>

<template>
  <div 
    class="flex flex-col w-full h-full overflow-y-auto overflow-x-visible custom-scrollbar transition-opacity duration-300"
    :class="isCollapsed ? 'opacity-0 pointer-events-none' : 'opacity-100'"
  >
    <div class="w-full flex flex-col gap-0.5 pb-20">
      <!-- Header -->
      <div class="flex items-center w-full h-9 transition-all pl-6 pr-3">
        <h3 class="text-sm font-semibold text-slate-900 dark:text-sidebar-foreground whitespace-nowrap">
          Gần đây
        </h3>
        <span
          v-if="chat.isUsingHistoryFallback"
          class="ml-2 text-[10px] font-medium text-amber-600"
        >
          Bản tạm
        </span>
      </div>

      <!-- History Items -->
      <div
        v-for="item in chat.conversations"
        :key="item.id"
        class="group relative flex items-center w-full px-2"
        style="z-index: auto;"
        :style="{ zIndex: activeMenuId === item.id ? '50' : 'auto' }"
      >
        <button
          @click="chat.loadConversation(item.id)"
          :class="cn(
            'flex items-center rounded-lg overflow-hidden cursor-pointer shrink-0 h-9 transition-all w-full text-sm hover:bg-slate-100 dark:hover:bg-sidebar-accent hover:text-slate-900 dark:hover:text-sidebar-accent-foreground focus-visible:ring-0 outline-none pl-4 pr-10',
            chat.currentConversationId === item.id || activeMenuId === item.id
              ? 'bg-slate-100 dark:bg-sidebar-accent text-slate-900 dark:text-sidebar-accent-foreground'
              : 'bg-transparent text-slate-600 dark:text-muted-foreground',
          )"
        >
          <span class="truncate font-medium">{{ item.title }}</span>
        </button>
        
        <!-- More Actions Button -->
        <div class="absolute right-3 opacity-0 group-hover:opacity-100 transition-opacity flex items-center z-10" :class="{ 'opacity-100': activeMenuId === item.id }">
          <button
            :ref="(el) => setMoreButtonRef(el, item.id)"
            type="button"
            class="p-1 text-slate-400 dark:text-muted-foreground hover:text-slate-600 dark:hover:text-sidebar-accent-foreground hover:bg-slate-200 dark:hover:bg-sidebar-accent rounded-md cursor-pointer transition-colors"
            :class="{ 'bg-slate-200 dark:bg-sidebar-accent text-slate-600 dark:text-sidebar-accent-foreground': activeMenuId === item.id }"
            @click.stop="toggleMenu(item.id)"
          >
            <MoreHorizontal class="h-4 w-4" />
          </button>
        </div>

        <!-- Dropdown Menu -->
        <div
          v-if="activeMenuId === item.id"
          :ref="(el) => activeDropdownRef = el as HTMLElement"
          class="absolute right-2 top-9 w-36 bg-white dark:bg-popover rounded-lg shadow-xl border border-slate-200 dark:border-border py-1.5 z-[100] animate-in fade-in zoom-in-95 duration-100"
        >
          <button
            class="flex items-center w-full px-3 py-1.5 text-xs font-medium text-slate-700 dark:text-popover-foreground hover:bg-slate-100 dark:hover:bg-accent transition-colors gap-2"
            @click.stop="openRenameModal(item.id, item.title)"
          >
            <Edit2 class="h-3.5 w-3.5 text-slate-400 dark:text-muted-foreground" />
            Đổi tên
          </button>
          <button
            class="flex items-center w-full px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10 transition-colors gap-2"
            @click.stop="confirmDelete(item.id)"
          >
            <Trash2 class="h-3.5 w-3.5 text-red-400" />
            Xóa
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Rename Modal -->
  <Teleport to="body">
    <div v-if="isRenameModalOpen" class="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <!-- Backdrop -->
      <div 
        class="absolute inset-0 bg-black/50 backdrop-blur-sm transition-opacity animate-in fade-in duration-300" 
        @click="closeRenameModal"
      />
      
      <!-- Modal Content -->
      <div class="relative bg-white dark:bg-card rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        <div class="p-6">
          <h3 class="text-lg font-bold text-slate-900 dark:text-foreground mb-1">
            Đổi tên cuộc trò chuyện
          </h3>
          <p class="text-sm text-slate-500 dark:text-muted-foreground mb-5">
            Nhập tên mới cho cuộc trò chuyện này.
          </p>

          <input
            ref="renameInputRef"
            v-model="renameTargetTitle"
            class="w-full px-4 py-2.5 bg-slate-50 dark:bg-chat-input border border-slate-200 dark:border-border rounded-xl outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 focus:bg-white dark:focus:bg-chat-input transition-all text-sm dark:text-foreground dark:placeholder:text-chat-placeholder"
            placeholder="Tên cuộc trò chuyện..."
            @keyup.enter="handleRename"
            @keyup.escape="closeRenameModal"
          />

          <div class="mt-8 flex justify-end gap-2.5">
            <button
              class="px-4 py-2 text-sm font-semibold text-slate-600 dark:text-muted-foreground hover:bg-slate-100 dark:hover:bg-accent rounded-xl transition-colors cursor-pointer"
              @click="closeRenameModal"
            >
              Huỷ
            </button>
            <button
              class="px-5 py-2 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-xl shadow-md shadow-blue-500/20 transition-all active:scale-[0.98] cursor-pointer"
              @click="handleRename"
            >
              Lưu thay đổi
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Delete Modal -->
  <Teleport to="body">
    <div v-if="isDeleteModalOpen" class="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <!-- Backdrop -->
      <div 
        class="absolute inset-0 bg-black/50 backdrop-blur-sm transition-opacity animate-in fade-in duration-300" 
        @click="closeDeleteModal"
      />
      
      <!-- Modal Content -->
      <div class="relative bg-white dark:bg-card rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        <div class="p-6">
          <h3 class="text-lg font-bold text-slate-900 dark:text-foreground mb-2">
            Bạn muốn xoá cuộc trò chuyện?
          </h3>
          <p class="text-sm text-slate-500 dark:text-muted-foreground leading-relaxed mb-6">
            Thao tác này sẽ xoá các câu lệnh, câu trả lời và ý kiến phản hồi, cũng như mọi nội dung bạn đã tạo.
          </p>

          <div class="flex justify-end gap-2.5">
            <button
              class="px-4 py-2 text-sm font-semibold text-slate-600 dark:text-muted-foreground hover:bg-slate-100 dark:hover:bg-accent rounded-xl transition-colors cursor-pointer"
              @click="closeDeleteModal"
            >
              Huỷ
            </button>
            <button
              class="px-5 py-2 text-sm font-semibold text-white bg-red-600 hover:bg-red-700 rounded-xl shadow-md shadow-red-500/20 transition-all active:scale-[0.98] cursor-pointer"
              @click="handleDelete"
            >
              Xoá
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
