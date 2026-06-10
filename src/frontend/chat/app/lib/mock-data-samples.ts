import type { Citation } from '~/types'

export const SAMPLE_CITATIONS: Citation[] = [
  {
    id: 'cit-1',
    document_id: 'doc-1',
    document: 'HR_Policy_2026.pdf',
    caption: 'Annual Leave',
    heading_path: ['Leave Entitlement', 'Annual Leave'],
  },
  {
    id: 'cit-2',
    document_id: 'doc-2',
    document: 'Employee_Handbook_v8.pdf',
    caption: 'Leave & Time Off',
    heading_path: ['Benefits', 'Leave & Time Off'],
  },
  {
    id: 'cit-3',
    document_id: 'doc-3',
    document: 'Benefits_Summary_2026.docx',
    caption: 'Statutory Holidays',
    heading_path: ['Benefits', 'Statutory Holidays'],
  },
]

export const SAMPLE_ANSWER = `New full-time joiners at FeatureMind are entitled to **25 annual leave days** per calendar year, accruing on a pro-rata basis from their first working day.`
