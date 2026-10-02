import { describe, expect, it } from 'vitest'

import type { Insight, InsightResult } from '../lib/types'
import { earlierLine, headline, latestLine, status, valueText } from './insightText'

const result = (fields: Partial<InsightResult> = {}): InsightResult => ({
  report_id: 'report-1',
  collected_at: '2025-09-05T02:45:00Z',
  value_text: '3.10',
  unit: 'ng/mL',
  value_canonical: '3.10',
  flag: 'low',
  ...fields,
})

const insight = (fields: Partial<Insight> = {}): Insight => ({
  patient_id: 'member-1',
  kind: 'outside_range',
  metric: {
    id: 'metric-ferritin',
    canonical_name: 'Ferritin',
    category: 'Iron studies',
    canonical_unit: 'ng/mL',
    description: null,
  },
  latest: result(),
  compared_with: result({
    collected_at: '2025-03-03T02:45:00Z',
    value_text: '48.3',
    value_canonical: '48.3',
    flag: 'normal',
  }),
  results_compared: 2,
  change: '-45.20',
  percent_change: -93.6,
  outside_in_a_row: 1,
  reference_low: '4.63',
  reference_high: '204.00',
  ...fields,
})

describe('outside the range', () => {
  it('says when a result moved out of the range, with the change in words', () => {
    const found = insight()
    expect(status(found)).toEqual({ label: 'Low', icon: 'arrowDown', alert: true })
    expect(headline(found)).toBe("Moved below the lab's range")
    expect(latestLine(found)).toBe(
      "Latest, 5 Sept 2025: 3.10 ng/mL (lab's range 4.63 – 204.00 ng/mL)",
    )
    expect(earlierLine(found)).toBe('Before, 3 Mar 2025: 48.3 ng/mL, so down 45.20 ng/mL (93.6%)')
  })

  it('says how long it has been outside, or that it is the first result', () => {
    expect(headline(insight({ compared_with: result({ flag: 'low' }), outside_in_a_row: 3 }))).toBe(
      "Below the lab's range in the last 3 results",
    )
    const first = insight({ compared_with: null, change: null, percent_change: null })
    expect(headline(first)).toBe("Below the lab's range (first result of this test)")
    expect(earlierLine(first)).toBeNull()
  })

  it('says when it swung from one side of the range to the other', () => {
    const swung = insight({
      latest: result({ flag: 'high', value_canonical: '250' }),
      compared_with: result({ flag: 'low' }),
    })
    expect(status(swung)).toEqual({ label: 'High', icon: 'arrowUp', alert: true })
    expect(headline(swung)).toBe("Moved from below to above the lab's range")
    expect(headline(insight({ compared_with: result({ flag: 'unknown' }) }))).toBe(
      "Below the lab's range",
    )
  })
})

describe('other findings', () => {
  it('back within the range', () => {
    const back = insight({
      kind: 'back_in_range',
      latest: result({ value_canonical: '20.5', flag: 'normal' }),
      compared_with: result({ flag: 'low', value_canonical: '8.2' }),
      change: '12.3',
      percent_change: 150,
    })
    expect(status(back)).toEqual({ label: 'In range', icon: 'check', alert: false })
    expect(headline(back)).toBe("Back within the lab's range, after being below it")
    expect(earlierLine(back)).toBe('Before, 5 Sept 2025: 8.2 ng/mL, so up 12.3 ng/mL (150%)')
  })

  it('a big change across several results, still within the range', () => {
    const rising = insight({
      kind: 'big_change',
      latest: result({ value_canonical: '5.5', flag: 'normal' }),
      compared_with: result({ value_canonical: '4.0', flag: 'normal' }),
      results_compared: 3,
      change: '1.5',
      percent_change: 37.5,
    })
    expect(status(rising)).toEqual({ label: 'Rising', icon: 'arrowUp', alert: false })
    expect(headline(rising)).toBe(
      "Rose by 37.5% across the last 3 results, still within the lab's range",
    )
    expect(earlierLine(rising)).toMatch(/^Earlier, /)

    const falling = insight({ kind: 'big_change', percent_change: -30, change: '-3.0' })
    expect(status(falling).label).toBe('Falling')
    expect(headline(falling)).toMatch(/^Fell by 30% across the last 2 results/)
  })
})

describe('values and ranges', () => {
  it('uses the printed value when it could not be put in the standard unit', () => {
    const found = insight({
      latest: result({ value_canonical: null, value_text: '12', unit: 'U' }),
    })
    expect(valueText(found.latest, found)).toBe('12 U')
  })

  it('words open-ended or missing ranges', () => {
    expect(latestLine(insight({ reference_low: null, reference_high: '30' }))).toMatch(
      /\(lab's range up to 30 ng\/mL\)$/,
    )
    expect(latestLine(insight({ reference_low: '13', reference_high: null }))).toMatch(
      /\(lab's range 13 ng\/mL or more\)$/,
    )
    expect(latestLine(insight({ reference_low: null, reference_high: null }))).toBe(
      'Latest, 5 Sept 2025: 3.10 ng/mL',
    )
  })

  it('says when nothing changed', () => {
    expect(earlierLine(insight({ change: '0.00', percent_change: 0 }))).toBe(
      'Before, 3 Mar 2025: 48.3 ng/mL, no change',
    )
  })
})
