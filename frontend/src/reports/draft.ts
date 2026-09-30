/**
 * The review form's working copy of a report: one editable draft per extracted row, checks
 * that mirror the backend's limits, and the body for POST /reports/{id}/confirm.
 */
import { indianDay } from '../lib/format'
import type { ConfirmedRow, ExtractedRow, MetricFlag } from '../lib/types'
import { compareDecimals, parseBound, previewFlag } from '../lib/values'

export interface DraftRow {
  key: string
  included: boolean
  /** Typed in by the user (a test the extraction missed), not extracted. */
  added: boolean
  raw_name: string
  canonical_metric_id: string | null
  value_text: string
  unit: string
  low: string
  high: string
  // As printed; shown for reference, sent back unchanged.
  reference_text: string | null
  reference_label: string | null
  sample_type: string | null
  method: string | null
  panel: string | null
  warnings: string[]
}

export type DraftField = 'raw_name' | 'value_text' | 'unit' | 'low' | 'high'
export type RowErrors = Partial<Record<DraftField, string>>

/** The backend's warning for a test it could not match (app/services/structuring); hidden
 * once the user picks a match. */
const UNKNOWN_TEST_PREFIX = 'Not in the metric dictionary'

let nextKey = 0
const newKey = () => `row-${String(nextKey++)}`

export function draftFromExtracted(row: ExtractedRow): DraftRow {
  return {
    key: newKey(),
    included: true,
    added: false,
    raw_name: row.raw_name,
    canonical_metric_id: row.canonical_metric_id,
    value_text: row.value_text,
    unit: row.unit ?? '',
    low: row.reference_low ?? '',
    high: row.reference_high ?? '',
    reference_text: row.reference_text,
    reference_label: row.reference_label,
    sample_type: row.sample_type,
    method: row.method,
    panel: row.panel,
    warnings: row.warnings,
  }
}

export function emptyDraft(): DraftRow {
  return {
    key: newKey(),
    included: true,
    added: true,
    raw_name: '',
    canonical_metric_id: null,
    value_text: '',
    unit: '',
    low: '',
    high: '',
    reference_text: null,
    reference_label: null,
    sample_type: null,
    method: null,
    panel: null,
    warnings: [],
  }
}

/** Warnings still worth showing for the row as it is now. */
export function visibleWarnings(row: DraftRow): string[] {
  return row.canonical_metric_id === null
    ? row.warnings
    : row.warnings.filter((warning) => !warning.startsWith(UNKNOWN_TEST_PREFIX))
}

/** Low/High as the server will compute it from the row as edited (invalid bounds count as
 * no bound until they are fixed). */
export function draftFlag(row: DraftRow): MetricFlag {
  return previewFlag(row.value_text, parseBound(row.low) ?? null, parseBound(row.high) ?? null)
}

/** Limits from backend/app/schemas/report.py (ConfirmedMetric). */
export function validateRow(row: DraftRow): RowErrors {
  const errors: RowErrors = {}
  const name = row.raw_name.trim()
  if (!name) errors.raw_name = 'Enter the test name.'
  else if (name.length > 200) errors.raw_name = 'Use at most 200 characters.'
  const value = row.value_text.trim()
  if (!value) errors.value_text = 'Enter the result.'
  else if (value.length > 100) errors.value_text = 'Use at most 100 characters.'
  if (row.unit.trim().length > 50) errors.unit = 'Use at most 50 characters.'

  const low = parseBound(row.low)
  const high = parseBound(row.high)
  const notNumber = 'Enter a number, like 12 or 4.5, or leave it empty.'
  if (low === undefined) errors.low = notNumber
  if (high === undefined) errors.high = notNumber
  if (low != null && high != null && compareDecimals(low, high) > 0) {
    errors.high = 'The end of the range must not be below its start.'
  }
  return errors
}

export function toConfirmedRow(row: DraftRow): ConfirmedRow {
  return {
    raw_name: row.raw_name.trim(),
    canonical_metric_id: row.canonical_metric_id,
    value_text: row.value_text.trim(),
    unit: row.unit.trim() || null,
    reference_low: parseBound(row.low) ?? null,
    reference_high: parseBound(row.high) ?? null,
    reference_text: row.reference_text,
    sample_type: row.sample_type,
    method: row.method,
  }
}

/** The collection time to send for a date picked in review: noon Indian time on that day,
 * or now if the day is today (so it is never in the future). */
export function collectedAtFor(day: string, now: Date = new Date()): string {
  return day === indianDay(now) ? now.toISOString() : `${day}T12:00:00+05:30`
}

export function validateCollectedDay(day: string, now: Date = new Date()): string | undefined {
  if (!day) return 'Enter the date the sample was collected.'
  if (day > indianDay(now)) return 'The collection date cannot be in the future.'
  return undefined
}
