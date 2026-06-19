import axiosClient from './axiosClient'
import type { EmployeeDetail, EmployeeDetailsResponse, EmployeeListResponse, EmploymentStatus, UpdateEmployeeRequest } from '~/types'

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

  async listEmployees(params?: {
    department?: string
    status?: EmploymentStatus
    limit?: number
    offset?: number
  }): Promise<EmployeeListResponse> {
    const response = await axiosClient.get<EmployeeListResponse>('/hr/admin/employees', { params, service: 'hr' })
    return response.data
  },

  async getEmployee(employeeId: string): Promise<EmployeeDetail> {
    const response = await axiosClient.get<EmployeeDetail>(`/hr/admin/employees/${employeeId}`, { service: 'hr' })
    return response.data
  },

  async getEmployeeDetails(employeeId: string): Promise<EmployeeDetailsResponse> {
    const response = await axiosClient.get<EmployeeDetailsResponse>(`/hr/admin/employees/${employeeId}/details`, { service: 'hr' })
    return response.data
  },

  async updateEmployee(employeeId: string, payload: UpdateEmployeeRequest): Promise<EmployeeDetail> {
    const response = await axiosClient.patch<EmployeeDetail>(`/hr/admin/employees/${employeeId}`, payload, { service: 'hr' })
    return response.data
  },

  async deleteEmployee(employeeId: string): Promise<void> {
    await axiosClient.delete(`/hr/admin/employees/${employeeId}`, { service: 'hr' })
  },
}

export default hrService
