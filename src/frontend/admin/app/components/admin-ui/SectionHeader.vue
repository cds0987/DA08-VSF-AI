<script setup lang="ts">
interface Props {
  title: string
  description?: string
}

defineProps<Props>()
</script>

<template>
  <div class="flex items-end justify-between gap-4">
    <div>
      <h2 class="text-[15px] font-semibold tracking-tight text-foreground">
        {{ title }}
      </h2>
      <p v-if="description" class="text-[12.5px] text-muted-foreground">{{ description }}</p>
    </div>
    <slot name="actions" />
  </div>
</template>
