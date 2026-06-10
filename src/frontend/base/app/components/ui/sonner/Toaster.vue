<script lang="ts" setup>
import type { ToasterProps } from "vue-sonner"
import { CircleCheck, Info, Loader2, OctagonX, TriangleAlert, X } from "@lucide/vue"
import { Toaster as Sonner } from "vue-sonner"
import { cn } from "@/lib/utils"
import "vue-sonner/style.css"

const props = defineProps<ToasterProps>()
</script>

<template>
  <Sonner
    :class="cn('toaster group', props.class)"
    style="z-index: 9999; isolation: isolate;"
    :toast-options="{
      classes: {
        toast: 'group toast !bg-background !text-foreground !border-border !shadow-lg !rounded-xl border',
        title: 'font-semibold',
        description: 'text-muted-foreground text-sm',
        actionButton: 'bg-primary text-primary-foreground',
        cancelButton: 'bg-muted text-muted-foreground',
        success: '!text-success',
        error: '!text-destructive',
        warning: '!text-warning',
        info: '!text-info',
      },
    }"
    v-bind="props"
  >
    <template #success-icon>
      <CircleCheck class="size-4 text-success" />
    </template>
    <template #info-icon>
      <Info class="size-4 text-info" />
    </template>
    <template #warning-icon>
      <TriangleAlert class="size-4 text-warning" />
    </template>
    <template #error-icon>
      <OctagonX class="size-4 text-destructive" />
    </template>
    <template #loading-icon>
      <Loader2 class="size-4 animate-spin" />
    </template>
    <template #close-icon>
      <X class="size-4" />
    </template>
  </Sonner>
</template>
