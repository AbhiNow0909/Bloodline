import { lazy, Suspense } from 'react'
import { Link, useParams } from 'react-router'

import { PageHeader } from '../components/PageHeader'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { buildChart } from '../history/chartData'
import { ApiError } from '../lib/api'
import { formatDate, pluralize } from '../lib/format'
import { useFamily, useMember, useMetricHistory } from '../lib/queries'
import type { HistoryPoint, MetricFlag } from '../lib/types'
import { rangeText } from '../lib/values'
import { FlagLabel } from '../reports/FlagLabel'
import { reportPath } from '../reports/labels'
import { NotDiagnosis } from '../reports/NotDiagnosis'
import { NotFound } from './NotFoundPage'

// Loaded only when a chart is shown, so the rest of the app stays small.
const TrendChart = lazy(() => import('../history/TrendChart'))

const FLAG_WORDS: Record<MetricFlag, string> = {
  low: 'Low',
  high: 'High',
  normal: 'in range',
  unknown: 'not compared',
}

const printed = (point: HistoryPoint) => `${point.value_text ?? ''} ${point.unit ?? ''}`.trim()

export function TestPage() {
  const { familyId = '', memberId = '', metricId = '' } = useParams()
  const family = useFamily(familyId)
  const member = useMember(memberId)
  const history = useMetricHistory(memberId, metricId)

  const error = family.error ?? member.error ?? history.error
  const misplaced = member.data !== undefined && member.data.family_id !== familyId
  if ((error instanceof ApiError && error.status === 404) || misplaced) {
    return <NotFound what="test" />
  }
  if (error) return <ErrorState error={error} />
  if (!family.data || !member.data || !history.data) return <LoadingState />

  const { metric, points } = history.data
  const memberName = member.data.display_name
  const model = buildChart(points)
  const latest = points.at(-1)
  const previous = points.at(-2)
  const first = points[0]
  const summary =
    latest && first
      ? `${metric.canonical_name}: ${pluralize(points.length, 'result', 'results')} from ` +
        `${formatDate(first.collected_at)} to ${formatDate(latest.collected_at)}. Latest ` +
        `${printed(latest)}, ${FLAG_WORDS[latest.flag]}.`
      : ''

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        crumbs={[
          { label: 'Families', to: '/families' },
          { label: family.data.name, to: `/families/${familyId}` },
          { label: memberName, to: `/families/${familyId}/members/${memberId}` },
          { label: metric.canonical_name },
        ]}
        title={metric.canonical_name}
        subtitle={`${metric.category}. ${memberName}'s results over time.`}
      />
      {metric.description && <p className="max-w-prose">{metric.description}</p>}

      {!latest ? (
        <EmptyState>No saved results for this test yet.</EmptyState>
      ) : (
        <>
          <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-muted">Latest result</dt>
              <dd className="flex flex-wrap items-baseline gap-x-2 text-lg font-semibold">
                {printed(latest)}
                <FlagLabel flag={latest.flag} />
              </dd>
            </div>
            <div>
              <dt className="text-muted">Collected</dt>
              <dd className="font-semibold">{formatDate(latest.collected_at)}</dd>
            </div>
            <div>
              <dt className="text-muted">Lab's range</dt>
              <dd className="font-semibold">{rangeText(latest)}</dd>
            </div>
            <div>
              <dt className="text-muted">Previous result</dt>
              <dd className="flex flex-wrap items-baseline gap-x-2 font-semibold">
                {previous ? (
                  <>
                    {printed(previous)} on {formatDate(previous.collected_at)}
                    <FlagLabel flag={previous.flag} />
                  </>
                ) : (
                  'None yet'
                )}
              </dd>
            </div>
          </dl>

          <section aria-labelledby="chart-heading" className="flex flex-col gap-3">
            <h2 id="chart-heading" className="text-lg font-semibold">
              Results over time, in {metric.canonical_unit}
            </h2>
            {model.points.length > 0 ? (
              <Suspense fallback={<LoadingState label="Loading the chart…" />}>
                <TrendChart model={model} summary={summary} />
              </Suspense>
            ) : (
              <p className="text-muted">None of these results are numbers that can be drawn.</p>
            )}
            {model.skipped.length > 0 && model.points.length > 0 && (
              <p className="max-w-prose text-sm text-muted">
                {pluralize(model.skipped.length, 'result is', 'results are')} not on the chart (not
                a number, or in a unit that could not be converted); see the table below.
              </p>
            )}
          </section>

          <section aria-labelledby="results-heading" className="flex flex-col gap-3">
            <h2 id="results-heading" className="text-lg font-semibold">
              All results
            </h2>
            <ResponsiveTable
              label={`All ${metric.canonical_name} results, newest first`}
              rows={[...points].reverse()}
              rowKey={(point, index) => `${point.report_id}-${String(index)}`}
              rowHeader={{ header: 'Collected', cell: (point) => formatDate(point.collected_at) }}
              columns={[
                {
                  header: 'Result',
                  mobileLabel: 'Result',
                  cell: (point) => (
                    <>
                      {printed(point)}
                      {point.unit_canonical &&
                        point.unit !== point.unit_canonical &&
                        point.value_canonical && (
                          <span className="block text-sm text-muted">
                            = {point.value_canonical} {point.unit_canonical}
                          </span>
                        )}
                    </>
                  ),
                },
                { header: "Lab's range", mobileLabel: 'Range', cell: rangeText },
                {
                  header: 'Compared with the range',
                  cell: (point) => <FlagLabel flag={point.flag} />,
                },
                {
                  header: 'Report',
                  cell: (point) => (
                    <Link
                      to={reportPath(familyId, { id: point.report_id, patient_id: memberId })}
                      className="text-edta underline underline-offset-4 hover:text-ink"
                    >
                      Open the report
                      <span className="sr-only"> of {formatDate(point.collected_at)}</span>
                    </Link>
                  ),
                },
              ]}
            />
          </section>
          <NotDiagnosis />
        </>
      )}
    </div>
  )
}
