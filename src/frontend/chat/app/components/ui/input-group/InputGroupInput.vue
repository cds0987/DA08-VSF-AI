<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { Input } from '~/components/ui/input'
import { cn } from '~/lib/utils'

const props = defineProps<{
  class?: HTMLAttributes['class']
  modelValue?: string | number
  type?: string
  placeholder?: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | number): void
}>()
</script>

<template>
  <Input
    data-slot="input-group-control"
    :type="type"
    :placeholder="placeholder"
    :disabled="disabled"
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :class="cn(
      'flex-1 rounded-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent',
      props.class,
    )"
  />
</template>
