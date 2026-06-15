import axiosClient from './axiosClient'

export interface EmployeeDepartment {
  user_id: string
  department: string
}

const hrService = {
  async listDepartments(): Promise<string[]> {
    const response = await axiosClient.get<{ departments: string[] }>('/hr/departments', { service: 'hr' })
    return response.data.departments
  },

  async getEmployeeDepartments(): Promise<Record<string, string>> {
    const response = await axiosClient.get<{ items: EmployeeDepartment[] }>('/hr/employees/departments', { service: 'hr' })
    return Object.fromEntries(response.data.items.map(e => [e.user_id, e.department]))
  },
}

export default hrService
