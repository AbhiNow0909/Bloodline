import { useEffect, useRef, type ReactNode } from 'react'

import { Breadcrumbs, type Crumb } from './Breadcrumbs'

interface PageHeaderProps {
  /** The path to this page; omitted at the top level, where it would only repeat the title. */
  crumbs?: Crumb[]
  title: string
  subtitle?: string
  leading?: ReactNode
  actions?: ReactNode
}

/** Breadcrumbs, the page heading and its actions. The heading takes focus when a page opens,
 * so screen readers announce the new page after a link is followed. */
export function PageHeader({ crumbs, title, subtitle, leading, actions }: PageHeaderProps) {
  const headingRef = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    document.title = `${title} – Bloodline`
    headingRef.current?.focus({ preventScroll: true })
  }, [title])

  return (
    <header className="flex flex-col gap-4">
      {crumbs && <Breadcrumbs items={crumbs} />}
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
        <div className="flex min-w-0 items-center gap-4">
          {leading}
          <div className="min-w-0">
            <h1
              ref={headingRef}
              tabIndex={-1}
              className="text-2xl font-bold tracking-tight break-words outline-none"
            >
              {title}
            </h1>
            {subtitle && <p className="mt-1 text-muted">{subtitle}</p>}
          </div>
        </div>
        {actions && <div className="flex flex-wrap gap-3">{actions}</div>}
      </div>
    </header>
  )
}
