<script setup lang="ts">
interface Props {
  title: string
  description?: string
}

defineProps<Props>()
</script>

<template>
  <div class="flex flex-col gap-2 bg-transparent px-8 pt-8 pb-4">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h1 class="text-[20px] font-semibold tracking-tight text-foreground">
          {{ title }}
        </h1>
        <p v-if="description" class="mt-0.5 text-[13px] text-muted-foreground">
          {{ description }}
        </p>
      </div>
      <div class="flex items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
    <div v-if="$slots.meta" class="flex items-center gap-3 text-[12px] text-muted-foreground">
      <slot name="meta" />
    </div>
  </div>
</template>
