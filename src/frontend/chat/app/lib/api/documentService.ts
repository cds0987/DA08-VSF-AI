import axiosClient from './axiosClient'
import type { DocumentFileResponse } from '~/types'

const documentService = {
  async getDocumentFile(documentId: string): Promise<DocumentFileResponse> {
    const response = await axiosClient.get<DocumentFileResponse>(`/${documentId}/file`, { service: 'document' })
    return response.data
  },

  // Inline preview qua domain mình: office đã convert -> application/pdf. Đi qua axios
  // để interceptor gắn Authorization; rồi tạo object-URL -> tab blob:vsfchat… (KHÔNG
  // nhảy presigned GCS). Khác getFileBlob (raw = bản gốc để tải về).
  async getPreviewBlob(documentId: string): Promise<Blob> {
    const response = await axiosClient.get<Blob>(`/${documentId}/file/preview`, {
      service: 'document',
      responseType: 'blob',
    })
    return response.data
  },

  // Bản gốc để tải về (Content-Disposition: attachment). Cùng đi qua axios để gắn auth.
  async getFileBlob(documentId: string): Promise<Blob> {
    const response = await axiosClient.get<Blob>(`/${documentId}/file/raw`, {
      service: 'document',
      responseType: 'blob',
    })
    return response.data
  },
}

export default documentService
