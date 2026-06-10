<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '~/lib/utils'

interface Props {
  class?: HTMLAttributes['class']
  size?: number
}

const props = withDefaults(defineProps<Props>(), {
  size: 32,
})
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 32 32"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    :class="cn(props.class)"
    role="img"
    aria-label="Octopus Logo"
  >
    <defs>
      <linearGradient
        id="octopusGradient"
        x1="0%"
        y1="0%"
        x2="100%"
        y2="100%"
      >
        <stop offset="0%" stop-color="#FF0000" />
        <stop offset="100%" stop-color="#E11D48" />
      </linearGradient>
    </defs>
    <path
      d="M16 2C12 2 9 5 9 9C9 11 10 13 10 15C10 16 9 17 8 17C6 17 5 18 5 20C5 22 6 24 8 24C9 24 10 23 10 22C10 23 11 24 12 24C13 24 14 23 14 22C14 24 15 26 16 26C17 26 18 24 18 22C18 23 19 24 20 24C21 24 22 23 22 22C22 23 23 24 24 24C26 24 27 22 27 20C27 18 26 17 24 17C23 17 22 16 22 15C22 13 23 11 23 9C23 5 20 2 16 2Z"
      fill="url(#octopusGradient)"
    />
    <circle
      cx="12"
      cy="10"
      r="2.5"
      fill="url(#octopusGradient)"
      opacity="0.9"
    />
    <circle
      cx="16"
      cy="8"
      r="2.5"
      fill="url(#octopusGradient)"
      opacity="0.9"
    />
    <circle
      cx="20"
      cy="10"
      r="2.5"
      fill="url(#octopusGradient)"
      opacity="0.9"
    />
  </svg>
</template>
