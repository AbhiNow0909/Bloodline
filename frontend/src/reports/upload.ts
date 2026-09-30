import { ApiError, MAX_UPLOAD_MB } from '../lib/api'

/** Why a file cannot be uploaded, checked before sending it; null if it can. */
export function fileProblem(file: File): string | null {
  const isPdf = file.type === 'application/pdf' || /\.pdf$/i.test(file.name)
  if (!isPdf) {
    return 'Choose a PDF file. Photos of paper reports cannot be read yet.'
  }
  if (file.size === 0) return 'This file is empty. Choose the PDF again.'
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    const size = (file.size / (1024 * 1024)).toFixed(1)
    return `This file is ${size} MB. Reports up to ${String(MAX_UPLOAD_MB)} MB can be uploaded.`
  }
  return null
}

/** The id of the report a duplicate upload matched (from the 409 response). */
export function duplicateOf(error: Error | null): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const { detail } = error
  if (typeof detail === 'object' && detail !== null && 'report_id' in detail) {
    return typeof detail.report_id === 'string' ? detail.report_id : null
  }
  return null
}
