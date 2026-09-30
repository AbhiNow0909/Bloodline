/**
 * Turns one test's history into what the trend chart draws. Values and ranges are plotted in
 * the test's canonical unit (the backend converts them), so results from labs that print
 * different units line up. Results that are not numbers, or whose unit could not be
 * converted, are left off the chart and listed in the table instead.
 */
import type { HistoryPoint, MetricFlag } from '../lib/types'

const DAY_MS = 24 * 60 * 60 * 1000

export interface ChartPoint {
  /** Collection time, in milliseconds. */
  t: number
  value: number
  /** The shaded reference band at this point: [low, high], open sides run to the chart's
   * edge. Null when the lab printed no range. */
  band: [number, number] | null
  flag: MetricFlag
  reading: HistoryPoint
}

export interface ChartModel {
  points: ChartPoint[]
  /** Results that cannot be drawn (e.g. "Negative", or a unit that could not be converted). */
  skipped: HistoryPoint[]
  xDomain: [number, number]
  xTicks: number[]
  yDomain: [number, number]
  yTicks: number[]
  /** When every result has the same range, one band across the whole chart. */
  sharedBand: [number, number] | null
}

const toNumber = (value: string | null): number | null => {
  if (value === null) return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

/** A step of 1, 2, 2.5 or 5 × 10ⁿ close to `rough`. */
function niceStep(rough: number): number {
  const power = 10 ** Math.floor(Math.log10(rough))
  const fraction = rough / power
  const nice =
    fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 2.5 ? 2.5 : fraction <= 5 ? 5 : 10
  return nice * power
}

/** A y-axis from below `low` to above `high` with round tick values. */
export function niceAxis(low: number, high: number, nonNegative: boolean) {
  let lo = low
  let hi = high
  if (lo === hi) {
    const pad = Math.abs(lo) * 0.2 || 1
    lo -= pad
    hi += pad
  } else {
    const pad = (hi - lo) * 0.1
    lo -= pad
    hi += pad
  }
  if (nonNegative) lo = Math.max(0, lo)
  const step = niceStep((hi - lo) / 5) // about five to seven ticks
  const start = Math.floor(lo / step) * step
  const end = Math.ceil(hi / step) * step
  const ticks: number[] = []
  // Rounded to the step's precision so 0.1 + 0.2 never shows as 0.30000000000000004.
  const decimals = Math.max(0, -Math.floor(Math.log10(step)) + 1)
  for (let tick = start; tick <= end + step / 2; tick += step) {
    ticks.push(Number(tick.toFixed(decimals)))
  }
  return { domain: [ticks[0] ?? start, ticks.at(-1) ?? end] as [number, number], ticks }
}

function timeAxis(times: number[]) {
  const first = Math.min(...times)
  const last = Math.max(...times)
  // A single date (or several on one day) gets a month either side; otherwise a small margin
  // so the first and last points are not cut in half by the chart's edge.
  const pad = last - first < DAY_MS ? 30 * DAY_MS : (last - first) * 0.04
  const domain: [number, number] = [first - pad, last + pad]
  const distinct = [...new Set(times)].sort((a, b) => a - b)
  const ticks =
    distinct.length <= 6
      ? distinct
      : Array.from({ length: 5 }, (_, i) => first + ((last - first) * i) / 4)
  return { domain, ticks }
}

export function buildChart(points: HistoryPoint[]): ChartModel {
  const plotted: Omit<ChartPoint, 'band'>[] = []
  const bounds: { low: number | null; high: number | null }[] = []
  const skipped: HistoryPoint[] = []

  for (const reading of points) {
    const value = toNumber(reading.value_canonical)
    if (value === null) {
      skipped.push(reading)
      continue
    }
    plotted.push({ t: Date.parse(reading.collected_at), value, flag: reading.flag, reading })
    bounds.push({
      low: toNumber(reading.reference_low_canonical),
      high: toNumber(reading.reference_high_canonical),
    })
  }

  const numbers = [
    ...plotted.map((p) => p.value),
    ...bounds.flatMap((b) => [b.low, b.high]).filter((n): n is number => n !== null),
  ]
  const nonNegative = numbers.every((n) => n >= 0)
  const y =
    numbers.length > 0
      ? niceAxis(Math.min(...numbers), Math.max(...numbers), nonNegative)
      : niceAxis(0, 1, true)
  const x = plotted.length > 0 ? timeAxis(plotted.map((p) => p.t)) : timeAxis([0])

  const [yMin, yMax] = y.domain
  const bandOf = ({ low, high }: { low: number | null; high: number | null }) =>
    low === null && high === null ? null : ([low ?? yMin, high ?? yMax] as [number, number])

  const chartPoints = plotted.map((point, index) => ({
    ...point,
    band: bandOf(bounds[index] ?? { low: null, high: null }),
  }))
  const first = bounds[0]
  const shared =
    first !== undefined && bounds.every((b) => b.low === first.low && b.high === first.high)
      ? bandOf(first)
      : null

  return {
    points: chartPoints,
    skipped,
    xDomain: x.domain,
    xTicks: x.ticks,
    yDomain: y.domain,
    yTicks: y.ticks,
    sharedBand: shared,
  }
}
