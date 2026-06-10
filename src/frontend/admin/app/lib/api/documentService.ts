import axiosClient from './axiosClient'
import type {
  Classification,
  DocumentDetail,
  DocumentFileResponse,
  DocumentListResponse,
  DocumentStatus,
  MessageResponse,
  UploadResponse,
} from '~/types'

const documentService = {
  async listDocuments(params?: {
    status?: DocumentStatus
    limit?: number
    offset?: number
  }): Promise<DocumentListResponse> {
    // '/' (không phải '') để interceptor ghép prefix -> /api/documents/ (url rỗng bị
    // interceptor bỏ qua, request lạc về '/').
    const response = await axiosClient.get<DocumentListResponse>('/', {
      params,
      service: 'document',
    })
    return response.data
  },

  async getDocument(documentId: string): Promise<DocumentDetail> {
    const response = await axiosClient.get<DocumentDetail>(`/${documentId}`, { service: 'document' })
    return response.data
  },

  async uploadDocument(input: {
    file: File
    classification: Classification
    allowedDepartments?: string[]
    allowedUserIds?: string[]
  }): Promise<UploadResponse> {
    const formData = new FormData()
    formData.append('file', input.file)
    formData.append('classification', input.classification)

    if (input.classification === 'secret' && input.allowedDepartments?.length) {
      formData.append('allowed_departments', input.allowedDepartments.join(','))
    }
    if (input.classification === 'top_secret' && input.allowedUserIds?.length) {
      formData.append('allowed_user_ids', input.allowedUserIds.join(','))
    }

    const response = await axiosClient.post<UploadResponse>('/upload', formData, {
      timeout: 120000,
      service: 'document',
    })
    return response.data
  },

  async getFileUrl(documentId: string): Promise<DocumentFileResponse> {
    const response = await axiosClient.get<DocumentFileResponse>(`/${documentId}/file`, { service: 'document' })
    return response.data
  },

  async deleteDocument(documentId: string): Promise<MessageResponse> {
    const response = await axiosClient.delete<MessageResponse>(`/${documentId}`, { service: 'document' })
    return response.data
  },
}

export default documentService
