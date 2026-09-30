/** The Bloodline mark (a folder holding a drop) and name. */
export function Wordmark({ className = '' }: { className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-2 text-lg font-bold tracking-tight ${className}`}
    >
      <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false" className="size-8">
        <path
          d="M3 8a2 2 0 0 1 2-2h7l3 3h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"
          fill="var(--color-edta)"
        />
        <path
          d="M16 13c-2.4 3-3.6 5-3.6 6.6a3.6 3.6 0 0 0 7.2 0c0-1.6-1.2-3.6-3.6-6.6z"
          fill="#fff"
        />
      </svg>
      Bloodline
    </span>
  )
}

const CAPS = ['--color-cap-lavender', '--color-cap-gold', '--color-cap-grey', '--color-cap-blue']

/** A small rack of sample tubes, drawn with the cap colours used for members. Decorative. */
export function TubeRack({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 132 92" aria-hidden="true" focusable="false" className={className}>
      {CAPS.map((cap, index) => {
        const x = 12 + index * 30
        return (
          <g key={cap}>
            <rect
              x={x + 3}
              y={16}
              width={18}
              height={62}
              rx={9}
              fill="#fff"
              stroke="var(--color-line)"
              strokeWidth={2}
            />
            <rect
              x={x + 5}
              y={48 - index * 5}
              width={14}
              height={28 + index * 5}
              rx={7}
              fill="var(--color-edta-soft)"
            />
            <rect x={x} y={6} width={24} height={16} rx={4} fill={`var(${cap})`} />
          </g>
        )
      })}
      <rect x={2} y={70} width={128} height={12} rx={3} fill="var(--color-edta)" />
    </svg>
  )
}
