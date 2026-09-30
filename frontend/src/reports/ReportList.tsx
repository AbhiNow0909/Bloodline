import { FileLink } from '../components/Cards'
import { Icon } from '../components/Icon'
import { ErrorState, LoadingState } from '../components/States'
import { pluralize } from '../lib/format'
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

/** A member's reports, newest first, each opening its own page. */
export function ReportList({ familyId, memberId }: { familyId: string; memberId: string }) {
  const reports = useReports(memberId)

  if (reports.isPending) return <LoadingState label="Loading reports…" />
  if (reports.isError) return <ErrorState error={reports.error} />
  if (reports.data.length === 0) {
    return <p className="text-muted">No reports yet.</p>
  }

  return (
    <ul className="flex flex-col gap-3">
      {reports.data.map((report) => {
        const detail = details(report)
        return (
          <li key={report.id}>
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
    </ul>
  )
}
