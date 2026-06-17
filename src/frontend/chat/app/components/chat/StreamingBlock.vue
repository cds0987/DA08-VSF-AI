<script setup lang="ts">
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

const props = defineProps<{ text: string }>()

const md = new MarkdownIt({ html: true, breaks: true, linkify: true })

const renderedContent = computed(() => {
  const html = props.text ? md.render(props.text) : '<p></p>'
  // Inject blinking cursor before the closing tag of the last block element
  return DOMPurify.sanitize(
    html.replace(/(<\/(?:p|li|h[1-6]|pre|blockquote)>)\s*$/, '<span class="streaming-cursor"></span>$1'),
  )
})
</script>

<template>
  <div class="rounded-xl bg-transparent px-5 pb-5 pt-4">
    <div
      class="ai-response-markdown prose prose-base prose-slate dark:prose-invert max-w-none font-medium text-slate-900 dark:text-foreground prose-p:font-medium prose-p:leading-relaxed prose-pre:bg-slate-50 dark:prose-pre:bg-background/50 prose-pre:border prose-pre:border-slate-200 dark:prose-pre:border-white/5 [overflow-wrap:anywhere]"
      v-html="renderedContent"
    />
  </div>
</template>

<style scoped>
:deep(.streaming-cursor) {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  vertical-align: middle;
  border-radius: 9999px;
  background-color: rgb(59 130 246);
  animation: streaming-blink 0.9s steps(1, end) infinite;
  box-shadow: 0 0 0.65rem rgb(59 130 246 / 0.35);
}

@keyframes streaming-blink {
  0%,
  45% {
    opacity: 1;
  }
  55%,
  100% {
    opacity: 0;
  }
}

.ai-response-markdown {
  --tw-prose-body: var(--foreground);
  --tw-prose-headings: var(--foreground);
  --tw-prose-lead: var(--foreground);
  --tw-prose-links: var(--primary);
  --tw-prose-bold: var(--foreground);
  --tw-prose-counters: var(--foreground);
  --tw-prose-bullets: var(--foreground);
  --tw-prose-quotes: var(--foreground);
  --tw-prose-captions: var(--muted-foreground);
  --tw-prose-kbd: var(--foreground);
  --tw-prose-code: var(--foreground);
  --tw-prose-pre-code: var(--foreground);
}
</style>
