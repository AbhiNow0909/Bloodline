import { describe, expect, it } from 'vitest'

import type { HistoryPoint } from '../lib/types'
import { buildChart, niceAxis } from './chartData'

const point = (fields: Partial<HistoryPoint>): HistoryPoint => ({
  patient_id: 'member-1',
  report_id: 'report-1',
  collected_at: '2025-03-03T02:35:00Z',
  canonical_metric_id: 'metric-ferritin',
  raw_name: 'FERRITIN',
  value_text: '48.3',
  value_numeric: '48.3',
  unit: 'ng/mL',
  value_canonical: '48.3',
  unit_canonical: 'ng/mL',
  reference_low: '4.63',
  reference_high: '204.00',
  reference_text: 'Women: 4.63 - 204.00 ng/ml',
  flag: 'normal',
  reference_low_canonical: '4.63',
  reference_high_canonical: '204.00',
  ...fields,
})

describe('niceAxis', () => {
  it('pads the values and uses round ticks', () => {
    expect(niceAxis(4.63, 204, true)).toEqual({
      domain: [0, 250],
      ticks: [0, 50, 100, 150, 200, 250],
    })
    expect(niceAxis(12, 15.5, true).ticks).toEqual([11, 12, 13, 14, 15, 16])
  })

  it('never shows floating-point noise', () => {
    const { ticks } = niceAxis(0.1, 0.7, true)
    expect(ticks.every((tick) => String(tick).length <= 4)).toBe(true)
  })

  it('handles a single value and negative values', () => {
    expect(niceAxis(5, 5, true).domain).toEqual([4, 6])
    expect(niceAxis(-2, 3, false).domain[0]).toBeLessThan(-2)
  })
})

describe('buildChart', () => {
  it('plots numeric results in the canonical unit, oldest first', () => {
    const model = buildChart([
      point({ collected_at: '2024-03-01T04:00:00Z', value_canonical: '60.1' }),
      point({ collected_at: '2025-03-03T02:35:00Z', value_canonical: '3.9', flag: 'low' }),
    ])
    expect(model.points.map((p) => [p.value, p.flag])).toEqual([
      [60.1, 'normal'],
      [3.9, 'low'],
    ])
    expect(model.skipped).toEqual([])
    expect(model.xTicks).toEqual([
      Date.parse('2024-03-01T04:00:00Z'),
      Date.parse('2025-03-03T02:35:00Z'),
    ])
  })

  it('draws one band across the chart when every result has the same range', () => {
    const model = buildChart([point({}), point({ collected_at: '2025-09-01T04:00:00Z' })])
    expect(model.sharedBand).toEqual([4.63, 204])
    expect(model.points[0]?.band).toEqual([4.63, 204])
  })

  it('follows each result’s own range when labs differ', () => {
    const model = buildChart([
      point({}),
      point({
        collected_at: '2025-09-01T04:00:00Z',
        reference_low_canonical: '13',
        reference_high_canonical: '150',
      }),
    ])
    expect(model.sharedBand).toBeNull()
    expect(model.points.map((p) => p.band)).toEqual([
      [4.63, 204],
      [13, 150],
    ])
  })

  it('runs an open-ended range to the chart’s edge', () => {
    const upTo = buildChart([
      point({
        value_canonical: '12.6',
        reference_low_canonical: null,
        reference_high_canonical: '30',
      }),
    ])
    expect(upTo.sharedBand).toEqual([upTo.yDomain[0], 30])
    const atLeast = buildChart([
      point({
        value_canonical: '40',
        reference_low_canonical: '20',
        reference_high_canonical: null,
      }),
    ])
    expect(atLeast.sharedBand).toEqual([20, atLeast.yDomain[1]])
  })

  it('has no band without a printed range', () => {
    const model = buildChart([
      point({ reference_low_canonical: null, reference_high_canonical: null }),
    ])
    expect(model.sharedBand).toBeNull()
    expect(model.points[0]?.band).toBeNull()
  })

  it('leaves text results and unconverted units off the chart', () => {
    const qualitative = point({
      value_text: 'Negative',
      value_numeric: null,
      value_canonical: null,
    })
    const model = buildChart([point({}), qualitative])
    expect(model.points).toHaveLength(1)
    expect(model.skipped).toEqual([qualitative])
  })

  it('gives a single result some room either side', () => {
    const model = buildChart([point({})])
    const t = Date.parse('2025-03-03T02:35:00Z')
    expect(model.xDomain[0]).toBeLessThan(t)
    expect(model.xDomain[1]).toBeGreaterThan(t)
    expect(model.xTicks).toEqual([t])
  })

  it('limits the date ticks for long histories', () => {
    const many = Array.from({ length: 9 }, (_, i) =>
      point({ collected_at: new Date(Date.UTC(2020 + i, 0, 15)).toISOString() }),
    )
    expect(buildChart(many).xTicks).toHaveLength(5)
  })
})
