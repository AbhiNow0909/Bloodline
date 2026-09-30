import { Link, Outlet } from 'react-router'

import { session } from '../lib/session'
import { useMe } from '../lib/queries'
import { Button } from './Button'
import { Wordmark } from './Wordmark'

export function AppLayout() {
  const me = useMe()

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:rounded-lg focus:bg-surface focus:px-4 focus:py-2"
      >
        Skip to content
      </a>
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
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
      <main id="main" className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6 sm:py-10">
        <Outlet />
      </main>
    </div>
  )
}
