import { describe, expect, it } from 'vitest'

import { compareDecimals, formatRange, parseBound, parseNumber, previewFlag } from './values'

describe('parseNumber (same rules as the backend)', () => {
  it.each([
    ['84.20', '84.20'],
    [' 1,234.5 ', '1234.5'],
    ['-3', '-3'],
    ['+0.5', '+0.5'],
    ['123456789012345678', '123456789012345678'], // 18 digits
  ])('reads %j as %j', (text, expected) => {
    expect(parseNumber(text)).toBe(expected)
  })

  it.each([
    '<0.5',
    '>1000',
    'Negative',
    'Trace',
    '',
    '1.',
    '.5',
    '1e3',
    '12 mg',
    '1234567890123456789',
  ])('keeps %j as text only', (text) => {
    expect(parseNumber(text)).toBeNull()
  })
})

describe('compareDecimals', () => {
  it.each([
    ['1', '1.0', 0],
    ['0.1', '0.10', 0],
    ['-0', '0.0', 0],
    ['9.99', '10', -1],
    ['10', '9.99', 1],
    ['-5', '3', -1],
    ['-10', '-9.5', -1],
    ['007.5', '7.50', 0],
    ['0.30000000000000004', '0.3', 1], // no floating-point rounding
  ])('compares %s with %s', (a, b, expected) => {
    expect(compareDecimals(a, b)).toBe(expected)
  })
})

describe('previewFlag', () => {
  it('uses inclusive bounds, like the server', () => {
    expect(previewFlag('12.0', '12', '15')).toBe('normal')
    expect(previewFlag('15', '12', '15.0')).toBe('normal')
    expect(previewFlag('11.99', '12', '15')).toBe('low')
    expect(previewFlag('15.01', '12', '15')).toBe('high')
  })

  it('handles one-sided ranges', () => {
    expect(previewFlag('30', null, '25')).toBe('high')
    expect(previewFlag('3', '4', null)).toBe('low')
  })

  it('is unknown without a number or a range', () => {
    expect(previewFlag('Negative', '0', '1')).toBe('unknown')
    expect(previewFlag('<0.5', null, '1')).toBe('unknown')
    expect(previewFlag('5', null, null)).toBe('unknown')
  })
})

describe('parseBound', () => {
  it('treats empty as no bound and reads plain numbers', () => {
    expect(parseBound('  ')).toBeNull()
    expect(parseBound(' 12.5 ')).toBe('12.5')
    expect(parseBound('0.000001')).toBe('0.000001')
  })

  it.each(['abc', '<5', '1.1234567', '12-15'])('rejects %j', (text) => {
    expect(parseBound(text)).toBeUndefined()
  })
})

describe('formatRange', () => {
  it('describes each kind of range', () => {
    expect(formatRange('12', '15')).toBe('12 – 15')
    expect(formatRange(null, '25')).toBe('Up to 25')
    expect(formatRange('4', null)).toBe('4 or more')
    expect(formatRange(null, null)).toBeNull()
  })
})
