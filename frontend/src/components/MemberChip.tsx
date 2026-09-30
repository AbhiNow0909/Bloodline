import { capColourFor, initialOf, type CapColour } from '../lib/format'

const CAPS: Record<CapColour, string> = {
  lavender: 'bg-cap-lavender',
  gold: 'bg-cap-gold',
  blue: 'bg-cap-blue',
  green: 'bg-cap-green',
  grey: 'bg-cap-grey',
}

const SIZES = { md: 'size-12 text-lg', lg: 'size-16 text-xl' } as const

/** A member's initial on a blood-tube cap colour. Decorative: the name is always shown
 * next to it, so it is hidden from screen readers and never the only identifier. */
export function MemberChip({
  id,
  name,
  size = 'md',
}: {
  id: string
  name: string
  size?: keyof typeof SIZES
}) {
  return (
    <span
      aria-hidden="true"
      className={`inline-grid shrink-0 place-items-center rounded-full font-bold text-ink ring-2 ring-surface ${CAPS[capColourFor(id)]} ${SIZES[size]}`}
    >
      {initialOf(name)}
    </span>
  )
}
