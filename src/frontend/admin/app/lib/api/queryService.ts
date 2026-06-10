import axiosClient from './axiosClient'
import type { AdminMetrics } from '~/types'

// Dùng axiosClient (resolve theo origin trình duyệt) thay vì Nuxt $fetch — $fetch ghép
// app.baseURL (/admin/) vào path tương đối -> /admin/api/query/... -> 404 khi chạy dưới
// sub-path. axiosClient.get với service:'query' ra đúng /api/query/admin/metrics same-origin.
export function useQueryService() {
  async function getAdminMetrics(from?: string, to?: string): Promise<AdminMetrics> {
    const res = await axiosClient.get<AdminMetrics>('/admin/metrics', {
      service: 'query',
      params: {
        ...(from ? { from } : {}),
        ...(to ? { to } : {}),
      },
    })
    return res.data
  }

  return { getAdminMetrics }
}
