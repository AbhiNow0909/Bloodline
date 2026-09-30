import { describe, expect, it } from 'vitest'

import {
  CAP_COLOURS,
  ageOn,
  capColourFor,
  describeMember,
  formatDate,
  initialOf,
  parseDateOnly,
  pluralize,
} from './format'

describe('dates', () => {
  it('parses a date of birth as a local calendar date', () => {
    const date = parseDateOnly('1968-03-01')
    expect([date.getFullYear(), date.getMonth(), date.getDate()]).toEqual([1968, 2, 1])
  })

  it('formats dates the Indian way without shifting the day', () => {
    expect(formatDate('1968-03-01')).toBe('1 Mar 1968')
    expect(formatDate('2025-12-31')).toBe('31 Dec 2025')
  })

  it.each([
    ['1968-03-01', new Date(2026, 1, 28), 57], // the day before the birthday
    ['1968-03-01', new Date(2026, 2, 1), 58], // on the birthday
    ['2000-02-29', new Date(2026, 1, 28), 25], // leap-day birthday, non-leap year
    ['2026-01-10', new Date(2026, 8, 30), 0],
  ])('age for %s on %s is %i', (dob, today, age) => {
    expect(ageOn(dob, today)).toBe(age)
  })
})

describe('describeMember', () => {
  const today = new Date(2026, 8, 30)

  it('shows sex and age', () => {
    expect(describeMember('female', '1968-03-01', today)).toBe('Female, 58 years')
    expect(describeMember('male', '2025-09-01', today)).toBe('Male, 1 year')
  })

  it('shows only sex without a date of birth', () => {
    expect(describeMember('male', null, today)).toBe('Male')
  })
})

describe('small helpers', () => {
  it('pluralizes', () => {
    expect(pluralize(0, 'member', 'members')).toBe('0 members')
    expect(pluralize(1, 'member', 'members')).toBe('1 member')
    expect(pluralize(3, 'member', 'members')).toBe('3 members')
  })

  it('gives each member a stable tube-cap colour', () => {
    const id = '7d0f1a52-3c1e-4f2b-9a51-2d1e0b7c9f10'
    expect(capColourFor(id)).toBe(capColourFor(id))
    expect(CAP_COLOURS).toContain(capColourFor(id))
    const colours = new Set(
      Array.from({ length: 50 }, (_, i) => capColourFor(`member-${String(i)}`)),
    )
    expect(colours.size).toBe(CAP_COLOURS.length)
  })

  it('takes the initial of a name', () => {
    expect(initialOf('  asha')).toBe('A')
    expect(initialOf('')).toBe('?')
  })
})
