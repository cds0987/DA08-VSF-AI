import axiosClient from './axiosClient'
import type { CreateUserRequest, CreatedUser, User } from '~/types'

export interface UserListResponse {
  items: User[]
  total: number
}

const userService = {
  async listUsers(params?: { is_active?: boolean; limit?: number; offset?: number }): Promise<UserListResponse> {
    const response = await axiosClient.get<UserListResponse>('/users', { params, service: 'user' })
    return response.data
  },

  async createUser(payload: CreateUserRequest): Promise<CreatedUser> {
    const response = await axiosClient.post<CreatedUser>('/users', payload, { service: 'user' })
    return response.data
  },

  async deactivateUser(userId: string): Promise<{ id: string; is_active: boolean }> {
    const response = await axiosClient.patch(`/users/${userId}/deactivate`, {}, { service: 'user' })
    return response.data
  },

  async reactivateUser(userId: string): Promise<{ id: string; is_active: boolean }> {
    const response = await axiosClient.patch(`/users/${userId}/reactivate`, {}, { service: 'user' })
    return response.data
  },
}

export default userService
