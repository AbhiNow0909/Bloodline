import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router'

import { Button } from '../components/Button'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { ErrorState, LoadingState } from '../components/States'
import { ApiError } from '../lib/api'
import { pluralize } from '../lib/format'
import { useDeleteReport, useFamily, useMember, useReport, useRetryReport } from '../lib/queries'
import type { Report } from '../lib/types'
import { LEAVE_WITHOUT_ASKING, reportTitle } from '../reports/labels'
import { PdfPreview } from '../reports/PdfPreview'
import { ReviewForm } from '../reports/ReviewForm'
import { SavedReadings } from '../reports/SavedReadings'
import { StatusBadge } from '../reports/StatusBadge'
import { NotFound } from './NotFoundPage'

const SLOW_AFTER_MS = 60_000

function Processing() {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const timer = setTimeout(() => {
      setSlow(true)
    }, SLOW_AFTER_MS)
    return () => {
      clearTimeout(timer)
    }
  }, [])

  return (
    <div role="status" className="flex max-w-prose flex-col gap-2 rounded-lg bg-surface p-5">
      <p className="flex items-center gap-2 font-semibold">
        <Icon name="clock" className="size-6 text-edta" />
        Reading the report
      </p>
      <p>
        Bloodline is finding the test results in the PDF. This usually takes a few seconds; this
        page updates by itself.
      </p>
      {slow && (
        <p className="font-semibold">
          This is taking longer than usual. If nothing changes in a few minutes, delete the report
          and upload it again.
        </p>
      )}
    </div>
  )
}

function Failed({ report }: { report: Report }) {
  const retry = useRetryReport(report.id)
  return (
    <div className="flex max-w-prose flex-col gap-4">
      <div role="alert" className="rounded-lg border border-alert/30 bg-alert-soft px-5 py-4">
        <p className="flex items-center gap-2 font-semibold text-alert">
          <Icon name="alert" />
          This report couldn't be read
        </p>
        <p className="mt-2">{report.failure_reason ?? 'Something went wrong while reading it.'}</p>
      </div>
      <p>
        If the problem was temporary (for example, the service was busy), try again. A scanned or
        photographed report cannot be read yet: delete it instead.
      </p>
      {retry.error && <ErrorState error={retry.error} />}
      <Button
        icon="refresh"
        className="w-fit"
        disabled={retry.isPending}
        onClick={() => {
          retry.mutate()
        }}
      >
        {retry.isPending ? 'Starting again…' : 'Try reading it again'}
      </Button>
    </div>
  )
}

export function ReportPage() {
  const { familyId = '', memberId = '', reportId = '' } = useParams()
  const family = useFamily(familyId)
  const member = useMember(memberId)
  const report = useReport(reportId)
  const navigate = useNavigate()
  const [deleting, setDeleting] = useState(false)
  const [savedCount, setSavedCount] = useState<number | null>(null)
  const savedRef = useRef<HTMLParagraphElement>(null)
  // After saving, bring the confirmation into view (the Save button is at the bottom).
  useEffect(() => {
    if (savedCount !== null) savedRef.current?.focus()
  }, [savedCount])
  // Created here with the report as loaded; the hook needs it for the member's report list.
  const deleteReport = useDeleteReport(report.data ?? { id: reportId, patient_id: memberId })

  const error = family.error ?? member.error ?? report.error
  const misplaced =
    (member.data !== undefined && member.data.family_id !== familyId) ||
    (report.data !== undefined && report.data.patient_id !== memberId)
  if ((error instanceof ApiError && error.status === 404) || misplaced) {
    return <NotFound what="report" />
  }
  if (error) return <ErrorState error={error} />
  if (!family.data || !member.data || !report.data) return <LoadingState />

  const current = report.data
  const memberName = member.data.display_name
  const memberPath = `/families/${familyId}/members/${memberId}`

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        crumbs={[
          { label: 'Families', to: '/families' },
          { label: family.data.name, to: `/families/${familyId}` },
          { label: memberName, to: memberPath },
          { label: reportTitle(current) },
        ]}
        title={reportTitle(current)}
        subtitle={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {current.lab_name}
            <StatusBadge status={current.status} />
          </span>
        }
        actions={
          <Button
            variant="secondary"
            icon="trash"
            onClick={() => {
              deleteReport.reset()
              setDeleting(true)
            }}
          >
            Delete report
          </Button>
        }
      />
      {current.status === 'processing' && <Processing />}
      {current.status === 'failed' && <Failed report={current} />}
      {current.status === 'pending_review' && (
        <div className="grid gap-8 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <div className="xl:order-2">
            <div className="xl:sticky xl:top-4">
              <PdfPreview reportId={current.id} />
            </div>
          </div>
          <div className="xl:order-1">
            <ReviewForm report={current} memberName={memberName} onSaved={setSavedCount} />
          </div>
        </div>
      )}
      {current.status === 'confirmed' && (
        <div className="flex flex-col gap-8">
          {savedCount !== null && (
            <p
              ref={savedRef}
              tabIndex={-1}
              role="status"
              className="flex items-center gap-2 rounded-lg bg-edta-soft px-4 py-3 font-semibold text-edta"
            >
              <Icon name="check" />
              Saved {pluralize(savedCount, 'value', 'values')} to {memberName}'s history.
            </p>
          )}
          <SavedReadings reportId={current.id} />
          <PdfPreview reportId={current.id} />
        </div>
      )}

      <ConfirmDialog
        open={deleting}
        onClose={() => {
          setDeleting(false)
        }}
        title="Delete this report?"
        confirmLabel="Delete report"
        pendingLabel="Deleting…"
        pending={deleteReport.isPending}
        error={deleteReport.error}
        onConfirm={() => {
          deleteReport.mutate(undefined, {
            onSuccess: () => {
              void navigate(memberPath, { replace: true, state: LEAVE_WITHOUT_ASKING })
            },
          })
        }}
      >
        <p>
          This permanently deletes the report, its PDF and any values saved from it. It can't be
          undone.
        </p>
      </ConfirmDialog>
    </div>
  )
}
