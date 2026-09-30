import { Link } from 'react-router'

import { Icon } from '../components/Icon'
import { MemberChip } from '../components/MemberChip'
import { ErrorState, LoadingState } from '../components/States'
import { formatDate, pluralize } from '../lib/format'
import { useFamilyOverview } from '../lib/queries'
import type { MemberOverview } from '../lib/types'
import { rangeText } from '../lib/values'
import { FlagLabel } from '../reports/FlagLabel'
import { NotDiagnosis } from '../reports/NotDiagnosis'
import { testPath } from './paths'

function MemberPanel({ familyId, overview }: { familyId: string; overview: MemberOverview }) {
  const { patient, out_of_range: flagged } = overview
  const memberPath = `/families/${familyId}/members/${patient.id}`
  return (
    <section
      aria-labelledby={`overview-${patient.id}`}
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
    >
      <div className="flex items-center gap-3">
        <MemberChip id={patient.id} name={patient.display_name} />
        <div className="min-w-0">
          <h3 id={`overview-${patient.id}`} className="font-semibold break-words">
            <Link to={memberPath} className="underline-offset-4 hover:text-edta hover:underline">
              {patient.display_name}
            </Link>
          </h3>
          <p className="text-sm text-muted">
            {overview.latest_report_at
              ? `Latest report ${formatDate(overview.latest_report_at)}, ${pluralize(overview.tracked_metric_count, 'test', 'tests')}`
              : 'No saved results yet'}
          </p>
        </div>
      </div>
      {overview.latest_report_at &&
        (flagged.length === 0 ? (
          <p className="flex items-center gap-2 text-sm">
            <Icon name="check" className="size-4 text-edta" />
            Every latest result is within the lab's range.
          </p>
        ) : (
          <ul className="flex flex-col gap-2 border-t border-line pt-3">
            {flagged.map((reading) => (
              <li key={`${reading.name}-${reading.collected_at}`}>
                <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="font-semibold">
                    {reading.canonical_metric_id ? (
                      <Link
                        to={testPath(familyId, patient.id, reading.canonical_metric_id)}
                        className="text-edta underline underline-offset-4 hover:text-ink"
                      >
                        {reading.name}
                      </Link>
                    ) : (
                      reading.name
                    )}
                  </span>
                  <FlagLabel flag={reading.flag} />
                </span>
                <span className="block text-sm text-muted">
                  {reading.value_text} {reading.unit} (range: {rangeText(reading)}),{' '}
                  {formatDate(reading.collected_at)}
                </span>
              </li>
            ))}
          </ul>
        ))}
    </section>
  )
}

/** Every member's latest out-of-range results, side by side. */
export function FamilyOverview({ familyId }: { familyId: string }) {
  const overview = useFamilyOverview(familyId)

  if (overview.isPending) return <LoadingState label="Loading the overview…" />
  if (overview.isError) return <ErrorState error={overview.error} />
  if (overview.data.members.length === 0) return null

  return (
    <section aria-labelledby="overview-heading" className="flex flex-col gap-4">
      <div>
        <h2 id="overview-heading" className="text-lg font-semibold">
          Outside the lab's range, by member
        </h2>
        <p className="text-muted">For each member, the tests whose latest result is Low or High.</p>
      </div>
      <div className="grid items-start gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {overview.data.members.map((member) => (
          <MemberPanel key={member.patient.id} familyId={familyId} overview={member} />
        ))}
      </div>
      <NotDiagnosis />
    </section>
  )
}
