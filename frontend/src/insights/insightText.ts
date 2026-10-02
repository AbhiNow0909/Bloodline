/**
 * Findings in words. The server computes every finding and number; this only says them, in the
 * test's standard unit (the unit its chart uses).
 */
import type { IconName } from '../components/Icon'
import { formatDate } from '../lib/format'
import type { Insight, InsightResult } from '../lib/types'

export interface Status {
  label: string
  icon: IconName
  /** Outside the lab's range: shown in the alert colour (always with the word and arrow). */
  alert: boolean
}

const rising = (insight: Insight) => (insight.percent_change ?? 0) > 0

/** The word for the status column: Low, High, Rising, Falling or In range. */
export function status(insight: Insight): Status {
  if (insight.kind === 'outside_range') {
    return insight.latest.flag === 'low'
      ? { label: 'Low', icon: 'arrowDown', alert: true }
      : { label: 'High', icon: 'arrowUp', alert: true }
  }
  if (insight.kind === 'back_in_range') return { label: 'In range', icon: 'check', alert: false }
  return rising(insight)
    ? { label: 'Rising', icon: 'arrowUp', alert: false }
    : { label: 'Falling', icon: 'arrowDown', alert: false }
}

const side = (result: InsightResult) => (result.flag === 'low' ? 'below' : 'above')

/** One sentence: what happened. */
export function headline(insight: Insight): string {
  const { latest, compared_with: earlier } = insight
  switch (insight.kind) {
    case 'outside_range':
      if (!earlier) return `${capitalise(side(latest))} the lab's range (first result of this test)`
      if (earlier.flag === latest.flag) {
        return `${capitalise(side(latest))} the lab's range in the last ${String(insight.outside_in_a_row)} results`
      }
      if (earlier.flag === 'normal') return `Moved ${side(latest)} the lab's range`
      if (earlier.flag === 'low' || earlier.flag === 'high') {
        return `Moved from ${side(earlier)} to ${side(latest)} the lab's range`
      }
      return `${capitalise(side(latest))} the lab's range`
    case 'back_in_range':
      return earlier
        ? `Back within the lab's range, after being ${side(earlier)} it`
        : "Back within the lab's range"
    case 'big_change':
      return `${rising(insight) ? 'Rose' : 'Fell'} by ${String(Math.abs(insight.percent_change ?? 0))}% across the last ${String(insight.results_compared)} results, still within the lab's range`
  }
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** "3.10 ng/mL": in the standard unit, or as printed when it could not be converted. */
export function valueText(result: InsightResult, insight: Insight): string {
  if (result.value_canonical !== null) {
    return `${result.value_canonical} ${insight.metric.canonical_unit}`
  }
  return `${result.value_text ?? ''} ${result.unit ?? ''}`.trim()
}

/** A range in words: "4.63 – 204.00 ng/mL", "up to 30 mg/L", "13 ng/mL or more", or null
 * when none was printed. */
export function rangeWords(low: string | null, high: string | null, unit: string | null) {
  const after = unit ? ` ${unit}` : ''
  if (low !== null && high !== null) return `${low} – ${high}${after}`
  if (high !== null) return `up to ${high}${after}`
  if (low !== null) return `${low}${after} or more`
  return null
}

/** "Latest, 5 Sept 2025: 3.10 ng/mL (lab's range 4.63 – 204.00 ng/mL)" */
export function latestLine(insight: Insight): string {
  const range = rangeWords(
    insight.reference_low,
    insight.reference_high,
    insight.metric.canonical_unit,
  )
  return `Latest, ${formatDate(insight.latest.collected_at)}: ${valueText(insight.latest, insight)}${range ? ` (lab's range ${range})` : ''}`
}

/** "Before, 3 Mar 2025: 48.3 ng/mL, so down 45.20 ng/mL (93.6%)" ("Earlier" when the change
 * spans more than two results), or null with nothing to compare. */
export function earlierLine(insight: Insight): string | null {
  const earlier = insight.compared_with
  if (!earlier) return null
  const label = insight.results_compared > 2 ? 'Earlier' : 'Before'
  let line = `${label}, ${formatDate(earlier.collected_at)}: ${valueText(earlier, insight)}`
  const { change, percent_change: percent } = insight
  if (change !== null) {
    const amount = change.replace(/^[-+]/, '')
    const moved = Number(change) === 0 ? 'no change' : change.startsWith('-') ? 'down' : 'up'
    line +=
      moved === 'no change'
        ? ', no change'
        : `, so ${moved} ${amount} ${insight.metric.canonical_unit}${percent !== null ? ` (${String(Math.abs(percent))}%)` : ''}`
  }
  return line
}
