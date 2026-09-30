import type { Sex } from './types'

const DATE_OPTIONS = { day: 'numeric', month: 'short', year: 'numeric' } as const
const DATE = new Intl.DateTimeFormat('en-IN', DATE_OPTIONS)
/** Lab reports print Indian time, and the backend treats days as Indian calendar days, so
 * timestamps are shown in Indian time whatever the device's time zone. */
export const REPORT_TIME_ZONE = 'Asia/Kolkata'
const DATE_IST = new Intl.DateTimeFormat('en-IN', { ...DATE_OPTIONS, timeZone: REPORT_TIME_ZONE })
const TIME_IST = new Intl.DateTimeFormat('en-IN', {
  hour: 'numeric',
  minute: '2-digit',
  timeZone: REPORT_TIME_ZONE,
})
const ISO_DAY_IST = new Intl.DateTimeFormat('en-CA', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  timeZone: REPORT_TIME_ZONE,
})

/** "YYYY-MM-DD" as a local calendar date (never shifted by a time zone). */
export function parseDateOnly(value: string): Date {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year ?? NaN, (month ?? NaN) - 1, day ?? NaN)
}

/** A date for people in India: "3 Mar 2025". Accepts "YYYY-MM-DD" (a calendar date) and ISO
 * timestamps (shown in Indian time). */
export function formatDate(value: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? DATE.format(parseDateOnly(value))
    : DATE_IST.format(new Date(value))
}

/** "3 Mar 2025, 8:05 am" in Indian time. */
export function formatDateTime(value: string): string {
  const date = new Date(value)
  return `${DATE_IST.format(date)}, ${TIME_IST.format(date)}`
}

/** The Indian calendar day of a timestamp as "YYYY-MM-DD" (for date inputs). */
export function indianDay(value: string | Date): string {
  return ISO_DAY_IST.format(typeof value === 'string' ? new Date(value) : value)
}

/** Completed years on `today` for someone born on `dateOfBirth` ("YYYY-MM-DD"). */
export function ageOn(dateOfBirth: string, today: Date = new Date()): number {
  const birth = parseDateOnly(dateOfBirth)
  let age = today.getFullYear() - birth.getFullYear()
  const hadBirthday =
    today.getMonth() > birth.getMonth() ||
    (today.getMonth() === birth.getMonth() && today.getDate() >= birth.getDate())
  if (!hadBirthday) age -= 1
  return age
}

export function describeMember(sex: Sex, dateOfBirth: string | null, today?: Date): string {
  const sexLabel = sex === 'female' ? 'Female' : 'Male'
  if (dateOfBirth === null) return sexLabel
  const age = ageOn(dateOfBirth, today)
  return `${sexLabel}, ${age} ${age === 1 ? 'year' : 'years'}`
}

export function pluralize(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`
}

/** Blood-tube cap colours, one per member, chosen from the id so it never changes. */
export const CAP_COLOURS = ['lavender', 'gold', 'blue', 'green', 'grey'] as const
export type CapColour = (typeof CAP_COLOURS)[number]

export function capColourFor(id: string): CapColour {
  let hash = 0
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  return CAP_COLOURS[hash % CAP_COLOURS.length] ?? 'lavender'
}

export function initialOf(name: string): string {
  return (name.trim()[0] ?? '?').toLocaleUpperCase('en-IN')
}
