<script setup lang="ts">
import type { AgentPlan, ChatMessage, Citation, NodeModel, PipelineStage, TraceEntry } from '~/types'
import UserBubble from './UserBubble.vue'
import FallbackBlock from './FallbackBlock.vue'
import AnswerBlock from './AnswerBlock.vue'
import Pipeline from './Pipeline.vue'

const props = defineProps<{
  messages: ChatMessage[]
  pipeline: number
  pipelineStages: PipelineStage[]
  streamingText: string
  streamingTurnKey: string
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

// Trong lúc stream, render câu trả lời bằng CHÍNH AnswerBlock (placeholder tạm) với turnKey
// trùng message-cuối -> khi xong Vue PATCH cùng node thay vì remount (hết flash). Cursor +
// markdown thô do AnswerBlock tự lo qua cờ `streaming`.
// Gắn LUÔN trace/plan/thoughts/models đang build live vào placeholder -> thanh MessageSteps
// (thu gọn, cao cố định) hiện ngay từ token đầu, lúc done KHÔNG chèn thêm gì phía trên answer
// -> nội dung "đứng yên", không bị dịch xuống.
const displayMessages = computed<ChatMessage[]>(() => {
  if (!props.streamingText) return props.messages
  return [
    ...props.messages,
    {
      id: props.streamingTurnKey,
      turnKey: props.streamingTurnKey,
      role: 'assistant',
      content: props.streamingText,
      streaming: true,
      timestamp: '',
      trace: props.traceLog,
      models: props.modelsUsed,
      thoughts: props.thoughts,
      plan: props.plan ?? undefined,
    },
  ]
})
</script>

<template>
  <div class="space-y-6">
    <template v-for="message in displayMessages" :key="message.turnKey ?? message.id">
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
  </div>
</template>
