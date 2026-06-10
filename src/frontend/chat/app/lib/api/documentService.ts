import axiosClient from './axiosClient'
import type { DocumentFileResponse } from '~/types'

const documentService = {
  async getDocumentFile(documentId: string): Promise<DocumentFileResponse> {
    const response = await axiosClient.get<DocumentFileResponse>(`/${documentId}/file`, { service: 'document' })
    return response.data
  },
}

export default documentService
