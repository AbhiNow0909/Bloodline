/**
 * Printed values and ranges, read the same way as the backend (app/services/normalization).
 * Used only to preview Low/High while a report is reviewed: on save the server recomputes
 * every number and flag from the reviewed text.
 */
import type { MetricFlag } from './types'

const NUMBER = /^[+-]?\d+(?:\.\d+)?$/
const MAX_DIGITS = 18

/** A plain printed number ("84.20", "1,234.5"); anything else ("<0.5", "Negative") is null.
 * Returned as a normalized string so no precision is lost. */
export function parseNumber(text: string): string | null {
  const candidate = text.trim().replace(/,/g, '')
  if (!NUMBER.test(candidate)) return null
  if ((candidate.match(/\d/g) ?? []).length > MAX_DIGITS) return null
  return candidate
}

/** Compare two plain decimal strings exactly (no floating-point rounding). */
export function compareDecimals(a: string, b: string): number {
  const split = (value: string) => {
    const negative = value.startsWith('-')
    const [whole = '0', fraction = ''] = value.replace(/^[+-]/, '').split('.')
    return {
      negative,
      whole: whole.replace(/^0+(?=\d)/, ''),
      fraction: fraction.replace(/0+$/, ''),
    }
  }
  const x = split(a)
  const y = split(b)
  const isZero = (n: typeof x) => /^0*$/.test(n.whole) && n.fraction === ''
  const sign = (n: typeof x) => (isZero(n) ? 0 : n.negative ? -1 : 1)
  if (sign(x) !== sign(y)) return sign(x) < sign(y) ? -1 : 1
  const direction = sign(x) < 0 ? -1 : 1
  if (x.whole.length !== y.whole.length) {
    return (x.whole.length < y.whole.length ? -1 : 1) * direction
  }
  const width = Math.max(x.fraction.length, y.fraction.length)
  const left = x.whole + x.fraction.padEnd(width, '0')
  const right = y.whole + y.fraction.padEnd(width, '0')
  if (left === right) return 0
  return (left < right ? -1 : 1) * direction
}

/** The flag the server will compute: inclusive bounds; no number or no range is "unknown". */
export function previewFlag(
  valueText: string,
  low: string | null,
  high: string | null,
): MetricFlag {
  const value = parseNumber(valueText)
  if (value === null || (low === null && high === null)) return 'unknown'
  if (low !== null && compareDecimals(value, low) < 0) return 'low'
  if (high !== null && compareDecimals(value, high) > 0) return 'high'
  return 'normal'
}

/** A range bound as typed in review: empty is "no bound"; otherwise a plain number with at
 * most 6 decimal places (what the server accepts). Returns undefined when it is not valid. */
export function parseBound(text: string): string | null | undefined {
  const trimmed = text.trim()
  if (trimmed === '') return null
  const value = parseNumber(trimmed)
  if (value === null) return undefined
  const decimals = value.split('.')[1]?.length ?? 0
  return decimals > 6 ? undefined : value
}

/** "12 – 15.5", "Up to 25", "4 or more" (bounds are inclusive), or null without a range. */
export function formatRange(low: string | null, high: string | null): string | null {
  if (low !== null && high !== null) return `${low} – ${high}`
  if (high !== null) return `Up to ${high}`
  if (low !== null) return `${low} or more`
  return null
}

/** A reading's printed range for tables: "12 – 15", "Up to 30", the printed text, or "–". */
export function rangeText(reading: {
  reference_low: string | null
  reference_high: string | null
  reference_text: string | null
}): string {
  return formatRange(reading.reference_low, reading.reference_high) ?? reading.reference_text ?? '–'
}
