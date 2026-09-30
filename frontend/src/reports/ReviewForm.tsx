import { useEffect, useState, type SubmitEvent } from 'react'
import { useBlocker } from 'react-router'

import { Button } from '../components/Button'
import { Dialog } from '../components/Dialog'
import { Icon } from '../components/Icon'
import { ErrorState, LoadingState } from '../components/States'
import { TextField } from '../components/TextField'
import { ApiError } from '../lib/api'
import { formatDateTime, indianDay, pluralize } from '../lib/format'
import { focusFirstField } from '../lib/forms'
import { useConfirmReport, useMetricDictionary, useReview } from '../lib/queries'
import { session } from '../lib/session'
import type { Report, ReportReview } from '../lib/types'
import {
  collectedAtFor,
  draftFromExtracted,
  emptyDraft,
  toConfirmedRow,
  validateCollectedDay,
  validateRow,
  visibleWarnings,
  type DraftField,
  type DraftRow,
  type RowErrors,
} from './draft'
import { isLeaveWithoutAsking } from './labels'
import { ReviewRow } from './ReviewRow'

const FIELD_ORDER: DraftField[] = ['raw_name', 'value_text', 'unit', 'low', 'high']
const SERVER_FIELDS: Record<string, DraftField> = {
  raw_name: 'raw_name',
  value_text: 'value_text',
  unit: 'unit',
  reference_low: 'low',
  reference_high: 'high',
}

interface ReviewFormProps {
  report: Report
  memberName: string
  onSaved: (count: number) => void
}

/** Loads the extracted rows, then shows the form. */
export function ReviewForm(props: ReviewFormProps) {
  const review = useReview(props.report.id, true)
  if (review.isPending) return <LoadingState label="Loading the values found in the report…" />
  if (review.isError) return <ErrorState error={review.error} />
  return <ReviewEditor {...props} review={review.data} />
}

function ReviewEditor({
  report,
  memberName,
  onSaved,
  review,
}: ReviewFormProps & { review: ReportReview }) {
  const dictionary = useMetricDictionary()
  const confirm = useConfirmReport(report.id)
  const [rows, setRows] = useState<DraftRow[]>(() => review.rows.map(draftFromExtracted))
  const [collectedDay, setCollectedDay] = useState(() =>
    report.collected_at ? indianDay(report.collected_at) : '',
  )
  const [rowErrors, setRowErrors] = useState<Record<string, RowErrors>>({})
  const [dateError, setDateError] = useState<string | undefined>()
  const [formError, setFormError] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  // Which row each sent metric came from, to show server errors on the right row.
  const [sentKeys, setSentKeys] = useState<string[]>([])

  const included = rows.filter((row) => row.included)
  const needChecking = included.filter((row) => visibleWarnings(row).length > 0).length

  // Unsaved corrections: ask before leaving the page. Never when signing out (a signed-out
  // user must not stay here) or when the report itself was just deleted.
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty &&
      !confirm.isPending &&
      session.get() !== null &&
      !isLeaveWithoutAsking(nextLocation.state) &&
      currentLocation.pathname !== nextLocation.pathname,
  )
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => {
      window.removeEventListener('beforeunload', warn)
    }
  }, [dirty])

  function updateRow(key: string, changes: Partial<DraftRow>) {
    setDirty(true)
    if (confirm.error) confirm.reset() // the server's messages are about the old values
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...changes } : row)))
    setRowErrors((current) =>
      key in current
        ? Object.fromEntries(Object.entries(current).filter(([k]) => k !== key))
        : current,
    )
  }

  function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const errors: Record<string, RowErrors> = {}
    for (const row of included) {
      const found = validateRow(row)
      if (Object.keys(found).length > 0) errors[row.key] = found
    }
    const dayChanged = !report.collected_at || collectedDay !== indianDay(report.collected_at)
    const dayError = dayChanged ? validateCollectedDay(collectedDay) : undefined
    setRowErrors(errors)
    setDateError(dayError)

    if (included.length === 0) {
      setFormError('Keep at least one value to save, or delete the report instead.')
      return
    }
    const invalidKeys = Object.keys(errors)
    if (dayError || invalidKeys.length > 0) {
      const count = invalidKeys.length + (dayError ? 1 : 0)
      setFormError(`${pluralize(count, 'thing needs', 'things need')} fixing before saving.`)
      const firstRow = included.find((row) => row.key in errors)
      const names = [
        ...(dayError ? ['collected_day'] : []),
        ...(firstRow
          ? FIELD_ORDER.filter((f) => errors[firstRow.key]?.[f]).map((f) => `${firstRow.key}.${f}`)
          : []),
      ]
      focusFirstField(form, names)
      return
    }

    setFormError(null)
    setSentKeys(included.map((row) => row.key))
    confirm.mutate(
      {
        ...(dayChanged ? { collected_at: collectedAtFor(collectedDay) } : {}),
        metrics: included.map(toConfirmedRow),
      },
      {
        onSuccess: () => {
          setDirty(false)
          onSaved(included.length)
        },
      },
    )
  }

  // Server-side field errors ("metrics.3.reference_low") shown on the row they belong to.
  const serverRowErrors: Record<string, RowErrors> = {}
  if (confirm.error instanceof ApiError) {
    for (const [path, message] of Object.entries(confirm.error.pathErrors)) {
      const [section, index, field] = path.split('.')
      const key = sentKeys[Number(index)]
      const draftField = field ? SERVER_FIELDS[field] : undefined
      if (section === 'metrics' && key && draftField) {
        serverRowErrors[key] = { ...serverRowErrors[key], [draftField]: message }
      }
    }
  }

  const printedFacts = [
    review.printed_age_years !== null ? `${String(review.printed_age_years)} years` : null,
    review.printed_sex,
  ].filter(Boolean)

  return (
    <form noValidate onSubmit={handleSubmit} className="flex flex-col gap-6">
      <p className="max-w-prose">
        Check each value against the PDF and correct anything that was read wrongly. Nothing is
        added to {memberName}'s history until you save.
      </p>

      {review.warnings.length > 0 && (
        <div
          role="alert"
          className="rounded-lg border border-alert/30 bg-alert-soft px-4 py-3 text-alert"
        >
          <p className="flex items-center gap-2 font-semibold">
            <Icon name="alert" />
            Check this first
          </p>
          <ul className="mt-2 flex list-disc flex-col gap-1 pl-10">
            {review.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}

      <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-3">
        <div>
          <dt className="text-muted">Lab</dt>
          <dd className="font-semibold">{report.lab_name ?? 'Not found in the report'}</dd>
        </div>
        <div>
          <dt className="text-muted">Printed on the report</dt>
          <dd className="font-semibold">
            {printedFacts.length > 0 ? printedFacts.join(', ') : 'No age or sex found'}
          </dd>
        </div>
        {report.collected_at && (
          <div>
            <dt className="text-muted">Sample collected</dt>
            <dd className="font-semibold">{formatDateTime(report.collected_at)}</dd>
          </div>
        )}
      </dl>

      <TextField
        label={report.collected_at ? 'Collection date' : 'Collection date (needed)'}
        hint={
          report.collected_at
            ? 'As read from the report. Change it only if it is wrong.'
            : 'The date could not be read from the report. Enter the day the sample was collected.'
        }
        type="date"
        name="collected_day"
        value={collectedDay}
        max={indianDay(new Date())}
        onChange={(event) => {
          setDirty(true)
          setCollectedDay(event.target.value)
          setDateError(undefined)
        }}
        error={dateError}
        className="max-w-60"
      />

      <section aria-labelledby="rows-heading" className="flex flex-col gap-4">
        <div>
          <h2 id="rows-heading" className="text-lg font-semibold">
            Values found
          </h2>
          <p className="text-muted">
            {pluralize(rows.length, 'test', 'tests')} found
            {needChecking > 0 ? `; ${pluralize(needChecking, 'needs', 'need')} checking` : ''}.
          </p>
          {dictionary.isError && (
            <p className="mt-1 text-sm text-muted">
              The list of known tests could not be loaded, so matches cannot be changed now.
            </p>
          )}
        </div>
        <ol className="flex flex-col gap-3">
          {rows.map((row) => (
            <li key={row.key}>
              <ReviewRow
                row={row}
                errors={rowErrors[row.key] ?? serverRowErrors[row.key] ?? {}}
                dictionary={dictionary.data}
                onChange={(changes) => {
                  updateRow(row.key, changes)
                }}
                onRemove={() => {
                  setRows((current) => current.filter((r) => r.key !== row.key))
                }}
              />
            </li>
          ))}
        </ol>
        <Button
          variant="secondary"
          icon="plus"
          className="w-fit"
          onClick={() => {
            setDirty(true)
            setRows((current) => [...current, emptyDraft()])
          }}
        >
          Add a test that was missed
        </Button>
      </section>

      <div className="sticky bottom-0 flex flex-col gap-3 border-t border-line bg-paper/95 py-4 backdrop-blur">
        {formError && <ErrorState error={new ApiError(0, formError)} />}
        {confirm.error && <ErrorState error={confirm.error} />}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-muted">
            {pluralize(included.length, 'value', 'values')} will be saved
            {rows.length > included.length
              ? `, ${String(rows.length - included.length)} left out`
              : ''}
            .
          </p>
          <Button type="submit" icon="check" disabled={confirm.isPending}>
            {confirm.isPending ? 'Saving…' : `Save to ${memberName}'s history`}
          </Button>
        </div>
      </div>

      <Dialog
        open={blocker.state === 'blocked'}
        onClose={() => {
          if (blocker.state === 'blocked') blocker.reset()
        }}
        title="Leave without saving?"
      >
        <p className="max-w-prose">
          Your corrections to this report will be lost. The report stays here, waiting for review.
        </p>
        {/* The safe choice comes first, so it has focus when the dialog opens. */}
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <Button
            onClick={() => {
              if (blocker.state === 'blocked') blocker.reset()
            }}
          >
            Stay and keep editing
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              if (blocker.state === 'blocked') blocker.proceed()
            }}
          >
            Leave without saving
          </Button>
        </div>
      </Dialog>
    </form>
  )
}
