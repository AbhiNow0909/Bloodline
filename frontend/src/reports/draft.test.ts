import { describe, expect, it } from 'vitest'

import { ROWS, UNKNOWN_TEST_WARNING } from '../test/reportData'
import {
  collectedAtFor,
  draftFlag,
  draftFromExtracted,
  emptyDraft,
  toConfirmedRow,
  validateCollectedDay,
  validateRow,
  visibleWarnings,
} from './draft'

const [haemoglobin, , cobalamin, urine] = ROWS.map(draftFromExtracted)
if (!haemoglobin || !cobalamin || !urine) throw new Error('fixture rows missing')

describe('drafts from extracted rows', () => {
  it('copy the printed values as editable text', () => {
    expect(haemoglobin).toMatchObject({
      included: true,
      added: false,
      raw_name: 'HAEMOGLOBIN',
      value_text: '13.5',
      unit: 'g/dL',
      low: '12.0',
      high: '15.0',
      canonical_metric_id: 'metric-hb',
    })
    expect(urine).toMatchObject({ unit: '', low: '', high: '' })
    expect(haemoglobin.key).not.toBe(urine.key)
  })

  it('preview the flag from the edited values', () => {
    expect(draftFlag(haemoglobin)).toBe('normal')
    expect(draftFlag({ ...haemoglobin, value_text: '16.2' })).toBe('high')
    expect(draftFlag({ ...haemoglobin, low: 'abc' })).toBe('normal') // invalid bound ignored
    expect(draftFlag(urine)).toBe('unknown')
  })

  it('hide the unknown-test warning once a match is chosen', () => {
    expect(visibleWarnings(cobalamin)).toEqual([UNKNOWN_TEST_WARNING])
    expect(visibleWarnings({ ...cobalamin, canonical_metric_id: 'metric-b12' })).toEqual([])
    const other = { ...cobalamin, warnings: ['Check the unit'], canonical_metric_id: 'metric-b12' }
    expect(visibleWarnings(other)).toEqual(['Check the unit'])
  })
})

describe('validateRow', () => {
  it('accepts an extracted row as it is', () => {
    expect(validateRow(haemoglobin)).toEqual({})
    expect(validateRow(urine)).toEqual({})
  })

  it('needs a name and a result', () => {
    expect(validateRow(emptyDraft())).toEqual({
      raw_name: 'Enter the test name.',
      value_text: 'Enter the result.',
    })
  })

  it('checks lengths against the server limits', () => {
    const errors = validateRow({
      ...haemoglobin,
      raw_name: 'x'.repeat(201),
      value_text: '1'.repeat(101),
      unit: 'u'.repeat(51),
    })
    expect(Object.keys(errors)).toEqual(['raw_name', 'value_text', 'unit'])
  })

  it('checks range bounds', () => {
    expect(validateRow({ ...haemoglobin, low: 'twelve' }).low).toMatch(/Enter a number/)
    expect(validateRow({ ...haemoglobin, high: '1.1234567' }).high).toMatch(/Enter a number/)
    expect(validateRow({ ...haemoglobin, low: '15', high: '12' }).high).toBe(
      'The end of the range must not be below its start.',
    )
    expect(validateRow({ ...haemoglobin, low: '12', high: '12.0' })).toEqual({})
  })
})

describe('toConfirmedRow', () => {
  it('sends trimmed text, bounds as exact strings and the printed context', () => {
    expect(
      toConfirmedRow({ ...haemoglobin, raw_name: ' Hb ', value_text: ' 13.50 ', low: ' 12 ' }),
    ).toEqual({
      raw_name: 'Hb',
      canonical_metric_id: 'metric-hb',
      value_text: '13.50',
      unit: 'g/dL',
      reference_low: '12',
      reference_high: '15.0',
      reference_text: 'Female: 12.0 - 15.0',
      sample_type: 'Whole blood',
      method: null,
    })
  })

  it('sends empty units and bounds as null', () => {
    expect(toConfirmedRow(urine)).toMatchObject({
      unit: null,
      reference_low: null,
      reference_high: null,
    })
  })
})

describe('collection date', () => {
  const now = new Date('2026-09-30T06:00:00Z') // 11:30 in India

  it('is noon Indian time on a past day, and now for today', () => {
    expect(collectedAtFor('2026-09-01', now)).toBe('2026-09-01T12:00:00+05:30')
    expect(collectedAtFor('2026-09-30', now)).toBe(now.toISOString())
  })

  it('must be given and not in the future (Indian calendar)', () => {
    expect(validateCollectedDay('', now)).toMatch(/Enter the date/)
    expect(validateCollectedDay('2026-10-01', now)).toMatch(/future/)
    expect(validateCollectedDay('2026-09-30', now)).toBeUndefined()
    // 20:00 UTC on 30 Sep is already 1 Oct in India.
    expect(validateCollectedDay('2026-10-01', new Date('2026-09-30T20:00:00Z'))).toBeUndefined()
  })
})
