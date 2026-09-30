import { Link, Outlet, useMatches } from 'react-router'

import { session } from '../lib/session'
import { useMe } from '../lib/queries'
import { Button } from './Button'
import { Wordmark } from './Wordmark'

/** A route with `handle: { wide: true }` gets a wider page (e.g. a report beside its PDF). */
function isWide(handle: unknown): boolean {
  return typeof handle === 'object' && handle !== null && 'wide' in handle && handle.wide === true
}

export function AppLayout() {
  const me = useMe()
  const wide = useMatches().some((match) => isWide(match.handle))
  const width = wide ? 'max-w-7xl' : 'max-w-5xl'

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:rounded-lg focus:bg-surface focus:px-4 focus:py-2"
      >
        Skip to content
      </a>
      <header className="border-b border-line bg-surface">
        <div
          className={`mx-auto flex ${width} flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6`}
        >
          <Link to="/families" className="rounded-lg text-ink">
            <Wordmark />
            <span className="sr-only">: your families</span>
          </Link>
          <div className="flex items-center gap-3">
            {me.data && (
              <span className="hidden text-muted sm:inline">
                Signed in as <span className="font-semibold text-ink">{me.data.display_name}</span>
              </span>
            )}
            <Button variant="secondary" icon="logout" onClick={session.clear}>
              Log out
            </Button>
          </div>
        </div>
      </header>
      <main id="main" className={`mx-auto w-full ${width} flex-1 px-4 py-8 sm:px-6 sm:py-10`}>
        <Outlet />
      </main>
    </div>
  )
}
