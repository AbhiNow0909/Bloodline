import type { Sex } from './types'

const DATE = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

/** "YYYY-MM-DD" as a local calendar date (never shifted by a time zone). */
export function parseDateOnly(value: string): Date {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year ?? NaN, (month ?? NaN) - 1, day ?? NaN)
}

/** A date for people in India: "3 Mar 2025". Accepts ISO timestamps and "YYYY-MM-DD". */
export function formatDate(value: string): string {
  const date = /^\d{4}-\d{2}-\d{2}$/.test(value) ? parseDateOnly(value) : new Date(value)
  return DATE.format(date)
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
