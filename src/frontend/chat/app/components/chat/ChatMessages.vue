<script setup lang="ts">
import type { ChatMessage, Citation, PipelineStage } from '~/types'
import UserBubble from './UserBubble.vue'
import FallbackBlock from './FallbackBlock.vue'
import AnswerBlock from './AnswerBlock.vue'
import Pipeline from './Pipeline.vue'
import StreamingBlock from './StreamingBlock.vue'

defineProps<{
  messages: ChatMessage[]
  pipeline: number
  pipelineStages: PipelineStage[]
  streamingText: string
}>()

const emit = defineEmits<{
  (e: 'open-citation', citation: Citation): void
  (e: 'feedback', messageId: string, score: 1 | -1): void
}>()
</script>

<template>
  <div class="space-y-6">
    <template v-for="message in messages" :key="message.id">
      <UserBubble v-if="message.role === 'user'" :text="message.content" :attachments="message.attachments" />
      <FallbackBlock v-else-if="message.fallback === true" />
      <AnswerBlock
        v-else
        :data="message"
        @open-citation="citation => emit('open-citation', citation)"
        @feedback="(messageId, score) => emit('feedback', messageId, score)"
      />
    </template>
    <Pipeline
      v-if="pipeline >= 0 && pipeline < pipelineStages.length"
      :stage="pipeline"
      :stages="pipelineStages"
    />
    <StreamingBlock
      v-if="pipeline === pipelineStages.length && streamingText"
      :text="streamingText"
    />
  </div>
</template>
