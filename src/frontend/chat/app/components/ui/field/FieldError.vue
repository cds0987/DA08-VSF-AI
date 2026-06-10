<script setup lang="ts">
import { computed, type HTMLAttributes } from 'vue'
import { cn } from '~/lib/utils'

const props = defineProps<{
  class?: HTMLAttributes['class']
  errors?: Array<{ message?: string } | undefined>
}>()

const hasSlot = defineSlots<{
  default?: () => any
}>()

const hasContent = computed(() => !!hasSlot.default || (props.errors && props.errors.length > 0))
</script>

<template>
  <div
    v-if="hasContent"
    role="alert"
    data-slot="field-error"
    :class="cn('text-destructive text-sm font-normal', props.class)"
  >
    <slot v-if="hasSlot.default" />
    <template v-else-if="errors && errors.length === 1 && errors[0]?.message">
      {{ errors[0].message }}
    </template>
    <ul v-else-if="errors && errors.length > 1" class="ml-4 flex list-disc flex-col gap-1">
      <template v-for="(error, index) in errors" :key="index">
        <li v-if="error?.message">
          {{ error.message }}
        </li>
      </template>
    </ul>
  </div>
</template>
