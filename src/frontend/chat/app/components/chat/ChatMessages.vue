<script setup lang="ts">
import type { AgentPlan, ChatMessage, Citation, NodeModel, PipelineStage, TraceEntry } from '~/types'
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
  thinkingStatus?: string
  traceLog?: TraceEntry[]
  modelsUsed?: NodeModel[]
  thoughts?: { node: string; text: string }[]
  plan?: AgentPlan | null
}>()

const emit = defineEmits<{
  (e: 'open-citation', citation: Citation): void
  (e: 'feedback', messageId: string, score: 1 | -1): void
  (e: 'retry', messageId: string): void
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
        @retry="messageId => emit('retry', messageId)"
      />
    </template>
    <Pipeline
      v-if="!streamingText && pipeline >= 0 && pipeline < pipelineStages.length"
      :trace-log="traceLog ?? []"
      :thinking-status="thinkingStatus"
      :models="modelsUsed"
      :thoughts="thoughts"
      :plan="plan"
      :is-thinking="pipeline >= 0 && pipeline < pipelineStages.length"
    />
    <StreamingBlock
      v-if="streamingText"
      :text="streamingText"
    />
  </div>
</template>
