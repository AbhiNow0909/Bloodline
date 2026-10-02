import { useEffect, useState, type ReactNode } from 'react'

import { Icon } from './Icon'

/** After this long, the note explains that the free AI service may be busy. */
const SLOW_AFTER_MS = 8_000

/** "Looking through…" while the AI works; after a few seconds, says why it may take a while. */
export function WaitingNote({ children }: { children: ReactNode }) {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const timer = setTimeout(() => {
      setSlow(true)
    }, SLOW_AFTER_MS)
    return () => {
      clearTimeout(timer)
    }
  }, [])
  return (
    <p className="flex items-start gap-2 text-muted">
      <Icon name="clock" className="mt-1 size-5 shrink-0 motion-safe:animate-pulse" />
      <span>
        {children}
        {slow && (
          <span className="block">
            Still working. When the free AI service is busy, this can take up to a minute.
          </span>
        )}
      </span>
    </p>
  )
}
