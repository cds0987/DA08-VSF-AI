<script setup lang="ts">
import { type HTMLAttributes } from 'vue'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '~/lib/utils'

const inputGroupAddonVariants = cva(
  'text-muted-foreground flex h-auto cursor-text items-center justify-center gap-2 py-1.5 text-sm font-medium select-none [&>svg:not([class*=\'size-\'])]:size-4 [&>kbd]:rounded-[calc(var(--radius)-5px)] group-data-[disabled=true]/input-group:opacity-50',
  {
    variants: {
      align: {
        'inline-start':
          'order-first pl-3 has-[>button]:ml-[-0.45rem] has-[>kbd]:ml-[-0.35rem]',
        'inline-end':
          'order-last pr-3 has-[>button]:mr-[-0.4rem] has-[>kbd]:mr-[-0.35rem]',
        'block-start':
          'order-first w-full justify-start px-3 pt-3 [.border-b]:pb-3 group-has-[>input]/input-group:pt-2.5',
        'block-end':
          'order-last w-full justify-start px-3 pb-3 [.border-t]:pt-3 group-has-[>input]/input-group:pb-2.5',
      },
    },
    defaultVariants: {
      align: 'inline-start',
    },
  },
)

interface Props {
  class?: HTMLAttributes['class']
  align?: VariantProps<typeof inputGroupAddonVariants>['align']
}

const props = withDefaults(defineProps<Props>(), {
  align: 'inline-start',
})

const handleClick = (e: MouseEvent) => {
  if ((e.target as HTMLElement).closest('button')) {
    return
  }
  const parent = (e.currentTarget as HTMLElement).parentElement
  parent?.querySelector('input')?.focus()
}
</script>

<template>
  <div
    role="group"
    data-slot="input-group-addon"
    :data-align="align"
    :class="cn(inputGroupAddonVariants({ align }), props.class)"
    @click="handleClick"
  >
    <slot />
  </div>
</template>
