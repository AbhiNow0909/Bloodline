import { Link } from 'react-router'

import { Icon } from './Icon'

export interface Crumb {
  label: string
  to?: string
}

/** Where you are, read like a file path: Families / Sharma Family / Mum. */
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-1 text-muted">
        {items.map((crumb, index) => (
          <li key={`${crumb.label}-${index}`} className="flex items-center gap-1">
            {index > 0 && <Icon name="chevron" className="size-4" />}
            {crumb.to ? (
              <Link to={crumb.to} className="underline-offset-4 hover:text-edta hover:underline">
                {crumb.label}
              </Link>
            ) : (
              <span aria-current="page" className="font-semibold text-ink">
                {crumb.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  )
}
