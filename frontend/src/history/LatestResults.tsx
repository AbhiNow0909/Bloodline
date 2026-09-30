import { Link } from 'react-router'

import { Icon } from '../components/Icon'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { ErrorState, LoadingState } from '../components/States'
import { formatDate, pluralize } from '../lib/format'
import { useCatalog } from '../lib/queries'
import type { CatalogEntry } from '../lib/types'
import { rangeText } from '../lib/values'
import { FlagLabel } from '../reports/FlagLabel'
import { NotDiagnosis } from '../reports/NotDiagnosis'
import { testPath } from './paths'

const isFlagged = (entry: CatalogEntry) =>
  entry.latest.flag === 'low' || entry.latest.flag === 'high'

const result = (entry: CatalogEntry) =>
  `${entry.latest.value_text ?? ''} ${entry.latest.unit ?? ''}`.trim()

function TestName({
  entry,
  familyId,
  memberId,
}: {
  entry: CatalogEntry
  familyId: string
  memberId: string
}) {
  if (!entry.metric) return <>{entry.name}</>
  return (
    <Link
      to={testPath(familyId, memberId, entry.metric.id)}
      className="text-edta underline underline-offset-4 hover:text-ink"
    >
      {entry.name}
    </Link>
  )
}

/** The member's dashboard: what is outside the range now, then every test's latest result,
 * grouped by category. Each test opens its chart. */
export function LatestResults({ familyId, memberId }: { familyId: string; memberId: string }) {
  const catalog = useCatalog(memberId)

  if (catalog.isPending) return <LoadingState label="Loading results…" />
  if (catalog.isError) return <ErrorState error={catalog.error} />
  if (catalog.data.length === 0) {
    return (
      <p className="max-w-prose text-muted">
        No results yet. They appear here once a report is reviewed and saved.
      </p>
    )
  }

  const flagged = catalog.data.filter(isFlagged)
  const groups = new Map<string, CatalogEntry[]>()
  for (const entry of catalog.data) {
    const category = entry.metric?.category ?? 'Other tests'
    groups.set(category, [...(groups.get(category) ?? []), entry])
  }

  return (
    <div className="flex flex-col gap-8">
      {flagged.length > 0 ? (
        <section
          aria-labelledby="attention-heading"
          className="rounded-lg border border-line border-l-4 border-l-alert bg-surface p-5"
        >
          <h3 id="attention-heading" className="flex items-center gap-2 font-semibold">
            <Icon name="alert" className="size-5 text-alert" />
            Outside the lab's range in the latest results
          </h3>
          <ul className="mt-3 flex flex-col gap-2">
            {flagged.map((entry) => (
              <li
                key={entry.metric?.id ?? entry.name}
                className="flex flex-wrap items-baseline gap-x-3"
              >
                <span className="font-semibold">
                  <TestName entry={entry} familyId={familyId} memberId={memberId} />
                </span>
                <span>{result(entry)}</span>
                <FlagLabel flag={entry.latest.flag} />
                <span className="text-sm text-muted">
                  (range: {rangeText(entry.latest)}), {formatDate(entry.latest.collected_at)}
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-3">
            <NotDiagnosis />
          </div>
        </section>
      ) : (
        <p className="flex items-center gap-2">
          <Icon name="check" className="size-5 text-edta" />
          Every latest result is within the lab's range.
        </p>
      )}

      {[...groups].map(([category, entries]) => (
        <section key={category} aria-label={category} className="flex flex-col gap-2">
          <h3 className="font-semibold">{category}</h3>
          <ResponsiveTable
            label={`${category}: latest results`}
            fixed
            rows={entries}
            rowKey={(entry) => entry.metric?.id ?? `raw:${entry.name}`}
            rowHeader={{
              header: 'Test',
              width: 'w-[28%]',
              cell: (entry) => <TestName entry={entry} familyId={familyId} memberId={memberId} />,
            }}
            columns={[
              { header: 'Latest result', mobileLabel: 'Latest', width: 'w-[20%]', cell: result },
              {
                header: 'Reference range',
                mobileLabel: 'Range',
                width: 'w-[17%]',
                cell: (e) => rangeText(e.latest),
              },
              {
                header: 'Compared with the range',
                width: 'w-[17%]',
                cell: (entry) => <FlagLabel flag={entry.latest.flag} />,
              },
              {
                header: 'Collected',
                mobileLabel: 'Collected',
                width: 'w-[18%]',
                cell: (entry) => (
                  <>
                    <span className="whitespace-nowrap">
                      {formatDate(entry.latest.collected_at)}
                    </span>
                    <span className="block text-sm text-muted">
                      {pluralize(entry.reading_count, 'result', 'results')}
                    </span>
                  </>
                ),
              },
            ]}
          />
          {!entries.every((entry) => entry.metric) && (
            <p className="max-w-prose text-sm text-muted">
              Tests that are not in Bloodline's list of known tests have no chart yet. They are kept
              as printed on the report.
            </p>
          )}
        </section>
      ))}
    </div>
  )
}
