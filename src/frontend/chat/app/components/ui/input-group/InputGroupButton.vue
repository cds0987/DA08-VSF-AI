<script setup lang="ts">
import { type HTMLAttributes } from 'vue'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '~/lib/utils'
import { Button } from '~/components/ui/button'

const inputGroupButtonVariants = cva(
  'text-sm shadow-none flex gap-2 items-center',
  {
    variants: {
      size: {
        xs: 'h-6 gap-1 px-2 rounded-[calc(var(--radius)-5px)] [&>svg:not([class*=\'size-\'])]:size-3.5 has-[>svg]:px-2',
        sm: 'h-8 px-2.5 gap-1.5 rounded-md has-[>svg]:px-2.5',
        'icon-xs':
          'size-6 rounded-[calc(var(--radius)-5px)] p-0 has-[>svg]:p-0',
        'icon-sm': 'size-8 p-0 has-[>svg]:p-0',
      },
    },
    defaultVariants: {
      size: 'xs',
    },
  },
)

interface Props {
  class?: HTMLAttributes['class']
  variant?: any // Button variant type
  size?: VariantProps<typeof inputGroupButtonVariants>['size']
  type?: 'button' | 'submit' | 'reset'
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'ghost',
  size: 'xs',
  type: 'button',
})
</script>

<template>
  <Button
    :type="type"
    :data-size="size"
    :variant="variant"
    :class="cn(inputGroupButtonVariants({ size }), props.class)"
  >
    <slot />
  </Button>
</template>
