import { useEffect, useRef, type ReactNode, type Ref } from 'react'
import { Link } from 'react-router'

import { Button } from '../components/Button'
import { Icon } from '../components/Icon'
import { WaitingNote } from '../components/WaitingNote'
import { errorMessage } from '../lib/api'
import { formatDate } from '../lib/format'
import { useExplanations } from '../lib/queries'
import type { FlaggedReading, Insight } from '../lib/types'
import { testPath } from '../history/paths'
import { NotDiagnosis } from '../reports/NotDiagnosis'
import { earlierLine, headline, latestLine, rangeWords, status, type Status } from './insightText'

function StatusCell({ value, className = '' }: { value: Status; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 font-semibold ${value.alert ? 'text-alert' : 'text-ink'} ${className}`}
    >
      <Icon name={value.icon} className="size-4 shrink-0" />
      {value.label}
    </span>
  )
}

/** One finding. The status word comes first, like the flag column of a lab report: its own
 * column on wider screens, the start of the first line in narrow places (phones, and each
 * member's card on the family page). */
function Row({
  status: value,
  title,
  compact,
  children,
}: {
  status: Status
  title: ReactNode
  compact: boolean
  children: ReactNode
}) {
  const wide = compact ? '' : 'sm:grid-cols-[7rem_minmax(0,1fr)] sm:items-start'
  return (
    <li className={`grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-3 py-3 ${wide}`}>
      <StatusCell value={value} className={compact ? '' : 'sm:row-span-2 sm:pt-0.5'} />
      <div>{title}</div>
      <div
        className={`col-span-2 flex flex-col gap-0.5 ${compact ? '' : 'sm:col-span-1 sm:col-start-2'}`}
      >
        {children}
      </div>
    </li>
  )
}

function FindingRow({
  insight,
  familyId,
  explanation,
  explanationRef,
  compact,
}: {
  insight: Insight
  familyId: string
  explanation: string | undefined
  explanationRef?: Ref<HTMLParagraphElement>
  compact: boolean
}) {
  const earlier = earlierLine(insight)
  return (
    <Row
      status={status(insight)}
      compact={compact}
      title={
        <Link
          to={testPath(familyId, insight.patient_id, insight.metric.id)}
          className="font-semibold text-edta underline underline-offset-4 hover:text-ink"
        >
          {insight.metric.canonical_name}
        </Link>
      }
    >
      <span>{headline(insight)}</span>
      <span className="text-sm text-muted">{latestLine(insight)}</span>
      {earlier && <span className="text-sm text-muted">{earlier}</span>}
      {explanation && (
        <p
          ref={explanationRef}
          tabIndex={-1}
          className="mt-2 max-w-prose border-l-2 border-edta pl-3"
        >
          <span className="font-semibold text-edta">In plain words: </span>
          {explanation}
        </p>
      )}
    </Row>
  )
}

/** A test outside the range that is not in Bloodline's list of known tests: no trend. */
function OtherRow({ reading, compact }: { reading: FlaggedReading; compact: boolean }) {
  const result = `${reading.value_text ?? ''} ${reading.unit ?? ''}`.trim()
  const range =
    rangeWords(reading.reference_low, reading.reference_high, reading.unit) ??
    reading.reference_text
  return (
    <Row
      status={
        reading.flag === 'low'
          ? { label: 'Low', icon: 'arrowDown', alert: true }
          : { label: 'High', icon: 'arrowUp', alert: true }
      }
      compact={compact}
      title={<span className="font-semibold">{reading.name}</span>}
    >
      <span>Outside the lab's range</span>
      <span className="text-sm text-muted">
        Latest, {formatDate(reading.collected_at)}: {result}
        {range && ` (lab's range ${range})`}
      </span>
    </Row>
  )
}

interface InsightsPanelProps {
  familyId: string
  memberId: string
  insights: Insight[]
  /** Tests outside the range that are not in the metric dictionary (no trends for them). */
  others: FlaggedReading[]
  /** Inside a member's card on the family page: no frame of its own. */
  compact?: boolean
}

/** What stands out in a member's results, computed on the server, with plain-language
 * explanations written by the AI when asked. */
export function InsightsPanel({
  familyId,
  memberId,
  insights,
  others,
  compact = false,
}: InsightsPanelProps) {
  const explanations = useExplanations(memberId, insights)
  const explained = new Map(
    (explanations.data?.explanations ?? []).map((e) => [`${e.metric_id}:${e.kind}`, e.text]),
  )
  const explanationOf = (insight: Insight) => explained.get(`${insight.metric.id}:${insight.kind}`)
  const answered = explanations.data !== undefined
  const nothingExplained = answered && !insights.some(explanationOf)
  const canAsk = insights.length > 0 && (!answered || nothingExplained)
  const firstExplained = insights.find(explanationOf)

  // The button goes away once explanations arrive; keep keyboard users in place by moving
  // focus to the first explanation (only when they have just arrived, not on a later visit).
  const firstExplanation = useRef<HTMLParagraphElement>(null)
  const previous = useRef(explanations.data)
  useEffect(() => {
    const arrived = previous.current === undefined && explanations.data !== undefined
    previous.current = explanations.data
    if (arrived && document.activeElement === document.body) firstExplanation.current?.focus()
  }, [explanations.data])

  const askButton = canAsk && (
    <Button
      variant={compact ? 'quiet' : 'secondary'}
      icon="chat"
      className={compact ? '-ml-2 self-start' : 'self-start'}
      disabled={explanations.pending}
      onClick={explanations.request}
    >
      {explanations.pending
        ? 'Explaining…'
        : explanations.error || nothingExplained
          ? 'Try again'
          : 'Explain in plain words'}
    </Button>
  )

  // Next to the button, so the reply is seen where it was asked for.
  const feedback = (
    <>
      {explanations.pending && <WaitingNote>Writing explanations…</WaitingNote>}
      {!explanations.pending && explanations.error && (
        <p role="alert" className="flex items-start gap-2 font-semibold text-alert">
          <Icon name="alert" className="mt-1 size-5 shrink-0" />
          {errorMessage(explanations.error)}
        </p>
      )}
      {!explanations.pending && nothingExplained && (
        <p className="text-muted">No explanations came back this time.</p>
      )}
    </>
  )

  const Frame = compact ? 'div' : 'section'
  return (
    <Frame
      aria-labelledby={compact ? undefined : `insights-${memberId}`}
      className={
        compact
          ? 'flex flex-col gap-2'
          : 'flex flex-col gap-3 rounded-lg border border-line bg-surface px-5 pt-4 pb-5'
      }
    >
      {!compact && (
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
          <div>
            <h3 id={`insights-${memberId}`} className="text-lg font-semibold">
              What stands out
            </h3>
            <p className="text-muted">
              From the saved reports: results outside the lab's range, back within it, or changing a
              lot.
            </p>
          </div>
          {askButton}
        </div>
      )}
      {!compact && feedback}

      <ul
        aria-label="Findings"
        className={`flex flex-col divide-y divide-line ${compact ? '' : 'border-t border-line'}`}
      >
        {insights.map((insight) => (
          <FindingRow
            key={`${insight.metric.id}:${insight.kind}`}
            insight={insight}
            familyId={familyId}
            explanation={explanationOf(insight)}
            explanationRef={insight === firstExplained ? firstExplanation : undefined}
            compact={compact}
          />
        ))}
        {others.map((reading) => (
          <OtherRow
            key={`${reading.name}:${reading.collected_at}`}
            reading={reading}
            compact={compact}
          />
        ))}
      </ul>

      {compact && askButton}
      {compact && feedback}

      {explanations.data && !nothingExplained && (
        <p className="max-w-prose text-sm text-muted">
          The explanations are written by an AI from the results above.{' '}
          {explanations.data.disclaimer}
        </p>
      )}
      {!compact && <NotDiagnosis />}
    </Frame>
  )
}
