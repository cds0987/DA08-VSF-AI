<script setup lang="ts">
import type { HRActionPayload } from '~/types'
import { useChatStore } from '~/stores/chat'

const props = defineProps<{ action: HRActionPayload }>()
const chat = useChatStore()
</script>

<template>
  <div class="mt-3 flex flex-wrap gap-2">
    <button
      v-for="s in action.suggestions"
      :key="s.label"
      class="rounded-lg border border-indigo-200 bg-indigo-50 dark:bg-indigo-900/20 px-3 py-1.5 text-sm font-medium text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-900/40 transition-colors"
      @click="chat.ask(s.query, [])"
    >
      {{ s.label }}
    </button>
  </div>
</template>
