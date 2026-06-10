<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { Textarea } from '~/components/ui/textarea'
import { cn } from '~/lib/utils'

const props = defineProps<{
  class?: HTMLAttributes['class']
  modelValue?: string | number
  placeholder?: string
  disabled?: boolean
  rows?: number
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | number): void
}>()
</script>

<template>
  <Textarea
    data-slot="input-group-control"
    :placeholder="placeholder"
    :disabled="disabled"
    :rows="rows"
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :class="cn(
      'flex-1 resize-none rounded-none border-0 bg-transparent py-3 shadow-none focus-visible:ring-0 dark:bg-transparent',
      props.class,
    )"
  />
</template>
