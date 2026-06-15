import axiosClient from './axiosClient'

const hrService = {
  async listDepartments(): Promise<string[]> {
    const response = await axiosClient.get<{ departments: string[] }>('/hr/departments', { service: 'hr' })
    return response.data.departments
  },
}

export default hrService
