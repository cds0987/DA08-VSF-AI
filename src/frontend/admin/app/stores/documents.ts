import { defineStore } from 'pinia'
import type { DocumentItem, DocumentStatus } from '~/types'
import documentService from '~/lib/api/documentService'

interface DocumentListParams {
  status?: DocumentStatus
  limit?: number
  offset?: number
}

export const useDocumentStore = defineStore('documents', () => {
  const items = ref<DocumentItem[]>([])
  const total = ref(0)
  const isLoading = ref(false)
  let lastParams: DocumentListParams | undefined
  let pollTimer: ReturnType<typeof setInterval> | null = null

  async function fetchDocuments(params?: DocumentListParams) {
    lastParams = params
    isLoading.value = true
    try {
      const response = await documentService.listDocuments(params)
      items.value = response.items
      total.value = response.total
    } finally {
      isLoading.value = false
    }
  }

  function startPolling(intervalMs = 4000) {
    if (pollTimer) return
    pollTimer = setInterval(() => {
      const hasPendingDocuments = items.value.some(
        document => document.status === 'queued' || document.status === 'processing',
      )
      if (!hasPendingDocuments) return
      void fetchDocuments(lastParams).catch((error) => {
        console.error('Failed to refresh document statuses:', error)
      })
    }, intervalMs)
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = null
  }

  return {
    items,
    total,
    isLoading,
    fetchDocuments,
    startPolling,
    stopPolling,
  }
})
