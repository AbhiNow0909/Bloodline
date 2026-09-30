import { Link } from 'react-router'

import { PageHeader } from '../components/PageHeader'

/** Shown for unknown addresses and for anything that does not exist or is not yours: the
 * two cases look the same on purpose, so nobody can tell that someone else's data exists. */
export function NotFound({ what = 'page' }: { what?: string }) {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        crumbs={[{ label: 'Families', to: '/families' }, { label: 'Not found' }]}
        title={`This ${what} can't be found`}
      />
      <p className="max-w-prose">
        It may have been deleted, or the address may be wrong.{' '}
        <Link to="/families" className="font-semibold text-edta underline underline-offset-4">
          Go to your families
        </Link>
      </p>
    </div>
  )
}

export function NotFoundPage() {
  return <NotFound />
}
