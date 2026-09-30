import { describe, expect, it } from 'vitest'

import { ApiError } from '../lib/api'
import { duplicateOf, fileProblem } from './upload'

const pdf = (name = 'report.pdf', type = 'application/pdf') =>
  new File(['%PDF-1.4'], name, { type })

function withSize(file: File, size: number): File {
  Object.defineProperty(file, 'size', { value: size })
  return file
}

describe('fileProblem', () => {
  it('accepts a PDF, by type or by name', () => {
    expect(fileProblem(pdf())).toBeNull()
    expect(fileProblem(pdf('REPORT.PDF', ''))).toBeNull()
  })

  it('refuses other files, empty files and files over the limit', () => {
    expect(fileProblem(pdf('scan.jpg', 'image/jpeg'))).toMatch(/Choose a PDF file/)
    expect(fileProblem(withSize(pdf(), 0))).toMatch(/empty/)
    expect(fileProblem(withSize(pdf(), 10 * 1024 * 1024))).toBeNull()
    expect(fileProblem(withSize(pdf(), 12.3 * 1024 * 1024))).toBe(
      'This file is 12.3 MB. Reports up to 10 MB can be uploaded.',
    )
  })
})

describe('duplicateOf', () => {
  it('reads the existing report id from a 409', () => {
    const error = new ApiError(409, 'Already uploaded', {}, {}, { message: 'x', report_id: 'r1' })
    expect(duplicateOf(error)).toBe('r1')
    expect(duplicateOf(new ApiError(409, 'Other conflict'))).toBeNull()
    expect(duplicateOf(new ApiError(422, 'x', {}, {}, { report_id: 'r1' }))).toBeNull()
    expect(duplicateOf(null)).toBeNull()
  })
})
