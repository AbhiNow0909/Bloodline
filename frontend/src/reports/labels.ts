import { formatDate } from '../lib/format'
import type { Report } from '../lib/types'

/** "Report of 3 Mar 2025" (collection date), or the upload date until that is known. */
export function reportTitle(report: Report): string {
  return report.collected_at
    ? `Report of ${formatDate(report.collected_at)}`
    : `Report uploaded ${formatDate(report.created_at)}`
}

export function reportPath(familyId: string, report: Pick<Report, 'id' | 'patient_id'>): string {
  return `/families/${familyId}/members/${report.patient_id}/reports/${report.id}`
}

/** Navigation state that skips the review form's "Leave without saving?" question (used
 * after the report itself is deleted). */
export const LEAVE_WITHOUT_ASKING = { leaveWithoutAsking: true } as const

export function isLeaveWithoutAsking(state: unknown): boolean {
  return typeof state === 'object' && state !== null && 'leaveWithoutAsking' in state
}
