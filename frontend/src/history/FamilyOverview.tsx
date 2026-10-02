import { Link } from 'react-router'

import { Icon } from '../components/Icon'
import { MemberChip } from '../components/MemberChip'
import { ErrorState, LoadingState } from '../components/States'
import { InsightsPanel } from '../insights/InsightsPanel'
import { formatDate, pluralize } from '../lib/format'
import { useFamilyOverview } from '../lib/queries'
import type { MemberOverview } from '../lib/types'
import { NotDiagnosis } from '../reports/NotDiagnosis'

function MemberPanel({ familyId, overview }: { familyId: string; overview: MemberOverview }) {
  const { patient, insights } = overview
  // Tests not in the dictionary have no trends; still list them when outside the range.
  const others = overview.out_of_range.filter((reading) => !reading.canonical_metric_id)
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
        (insights.length + others.length === 0 ? (
          <p className="flex items-center gap-2 text-sm">
            <Icon name="check" className="size-4 text-edta" />
            Every latest result is within the lab's range, with no big changes.
          </p>
        ) : (
          <div className="border-t border-line">
            <InsightsPanel
              compact
              familyId={familyId}
              memberId={patient.id}
              insights={insights}
              others={others}
            />
          </div>
        ))}
    </section>
  )
}

/** What stands out in every member's results, side by side. */
export function FamilyOverview({ familyId }: { familyId: string }) {
  const overview = useFamilyOverview(familyId)

  if (overview.isPending) return <LoadingState label="Loading the overview…" />
  if (overview.isError) return <ErrorState error={overview.error} />
  if (overview.data.members.length === 0) return null

  return (
    <section aria-labelledby="overview-heading" className="flex flex-col gap-4">
      <div>
        <h2 id="overview-heading" className="text-lg font-semibold">
          What stands out, by member
        </h2>
        <p className="text-muted">
          For each member: results outside the lab's range, back within it, or changing a lot.
        </p>
      </div>
      <div className="grid items-start gap-4 md:grid-cols-2">
        {overview.data.members.map((member) => (
          <MemberPanel key={member.patient.id} familyId={familyId} overview={member} />
        ))}
      </div>
      <NotDiagnosis />
    </section>
  )
}
