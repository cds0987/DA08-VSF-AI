import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('../../../', import.meta.url)

async function read(path: string) {
  return await readFile(new URL(path, root), 'utf8')
}

test('persists and restores distinct server conversations', async () => {
  const [store, api, router, querySchema] = await Promise.all([
    read('frontend/chat/app/stores/chat.ts'),
    read('frontend/chat/app/lib/api/queryService.ts'),
    read('query-service/app/interfaces/api/routers/conversations.py'),
    read('query-service/app/interfaces/api/schemas/query.py'),
  ])

  assert.doesNotMatch(store, /BACKEND_CONVERSATION_ID|backend-conversation/)
  assert.match(store, /return crypto\.randomUUID\(\)/)
  assert.match(store, /conversation_id: currentConversationId\.value/)
  assert.match(store, /fetchAllConversations/)
  assert.match(store, /offset \+= pageSize/)
  assert.match(store, /localOnly/)
  assert.match(store, /isConversationId/)
  assert.match(store, /abortController\?\.abort\(\)/)
  assert.match(store, /fetchConversation\(id\)/)
  // URL-based routing: currentConversationId là ref(null), không còn dùng localStorage key
  assert.match(store, /currentConversationId = ref<string \| null>\(null\)/)
  assert.match(store, /isConversationLoading/)

  assert.match(api, /fetchConversation\(id: string/)
  assert.match(api, /deleteConversation\(id: string/)
  assert.match(router, /@router\.get\("\/conversations\/\{conversation_id\}"/)
  assert.match(router, /@router\.patch\(/)
  assert.match(router, /@router\.delete\(/)
  assert.match(router, /limit: int = Query\(default=500/)
  assert.match(querySchema, /conversation_id: UUID \| None/)
})
