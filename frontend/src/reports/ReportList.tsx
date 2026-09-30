import { FileLink } from '../components/Cards'
import { Icon } from '../components/Icon'
import { ErrorState, LoadingState } from '../components/States'
import { indianDay, pluralize } from '../lib/format'
import { useReports } from '../lib/queries'
import type { ReportSummary } from '../lib/types'
import { reportPath, reportTitle } from './labels'
import { StatusBadge } from './StatusBadge'

function details(report: ReportSummary): string | null {
  if (report.status !== 'confirmed') return report.lab_name
  const values = pluralize(report.metric_count, 'value', 'values')
  const flagged =
    report.flagged_count === 0
      ? 'none outside the range'
      : `${String(report.flagged_count)} outside the range`
  return [report.lab_name, `${values}, ${flagged}`].filter(Boolean).join('. ')
}

/** The year a report sits under on the timeline (collection date, else upload date). */
const yearOf = (report: ReportSummary) =>
  indianDay(report.collected_at ?? report.created_at).slice(0, 4)

/** A member's reports as a timeline, newest first, each opening its own page. */
export function ReportList({ familyId, memberId }: { familyId: string; memberId: string }) {
  const reports = useReports(memberId)

  if (reports.isPending) return <LoadingState label="Loading reports…" />
  if (reports.isError) return <ErrorState error={reports.error} />
  if (reports.data.length === 0) {
    return <p className="text-muted">No reports yet.</p>
  }

  return (
    <ol
      aria-label="Reports, newest first"
      className="ml-2 flex flex-col gap-3 border-l-2 border-line pl-6"
    >
      {reports.data.map((report, index) => {
        const detail = details(report)
        const year = yearOf(report)
        const newYear = index === 0 || year !== yearOf(reports.data[index - 1] ?? report)
        return (
          <li key={report.id} className="relative">
            {newYear && <span className="mb-1 block text-sm font-semibold text-muted">{year}</span>}
            <span
              aria-hidden="true"
              className={`absolute -left-[31px] size-3 rounded-full ring-4 ring-paper ${
                newYear ? 'top-[3.25rem]' : 'top-7'
              } ${report.status === 'confirmed' ? 'bg-edta' : 'bg-muted'}`}
            />
            <FileLink to={reportPath(familyId, report)}>
              <Icon name="file" className="size-6 text-edta" />
              <span className="flex min-w-0 flex-1 flex-col gap-1 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
                <span className="min-w-0">
                  <span className="block font-semibold">{reportTitle(report)}</span>
                  {detail && <span className="block text-muted">{detail}</span>}
                </span>
                <StatusBadge status={report.status} />
              </span>
            </FileLink>
          </li>
        )
      })}
    </ol>
  )
}
