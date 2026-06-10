<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { Separator } from '~/components/ui/separator'
import { cn } from '~/lib/utils'

const props = defineProps<{
  class?: HTMLAttributes['class']
}>()

const hasSlot = defineSlots<{
  default?: () => any
}>()
</script>

<template>
  <div
    data-slot="field-separator"
    :data-content="!!hasSlot.default"
    :class="cn(
      'relative -my-2 h-5 text-sm group-data-[variant=outline]/field-group:-mb-2',
      props.class,
    )"
  >
    <Separator class="absolute inset-0 top-1/2" />
    <span
      v-if="hasSlot.default"
      class="bg-background text-muted-foreground relative mx-auto block w-fit px-2"
      data-slot="field-separator-content"
    >
      <slot />
    </span>
  </div>
</template>
