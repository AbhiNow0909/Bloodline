import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'

import { Button } from '../components/Button'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Dialog } from '../components/Dialog'
import { Icon } from '../components/Icon'
import { MemberChip } from '../components/MemberChip'
import { MemberForm } from '../components/MemberForm'
import { PageHeader } from '../components/PageHeader'
import { ErrorState, LoadingState } from '../components/States'
import { ApiError } from '../lib/api'
import { ageOn, formatDate, pluralize } from '../lib/format'
import { useDeleteMember, useFamily, useMember, useUpdateMember } from '../lib/queries'
import { ReportList } from '../reports/ReportList'
import { UploadReport } from '../reports/UploadReport'
import { NotFound } from './NotFoundPage'

type OpenDialog = 'edit' | 'delete' | null

export function MemberPage() {
  const { familyId = '', memberId = '' } = useParams()
  const family = useFamily(familyId)
  const member = useMember(memberId)
  const updateMember = useUpdateMember(memberId, familyId)
  const deleteMember = useDeleteMember(memberId, familyId)
  const navigate = useNavigate()
  const [dialog, setDialog] = useState<OpenDialog>(null)

  const error = family.error ?? member.error
  // A member opened under another family's URL is treated like one that does not exist.
  const misplaced = member.data !== undefined && member.data.family_id !== familyId
  if ((error instanceof ApiError && error.status === 404) || misplaced) {
    return <NotFound what="family member" />
  }
  if (error) return <ErrorState error={error} />
  if (!family.data || !member.data) return <LoadingState />

  const { display_name: name, sex, date_of_birth: dateOfBirth } = member.data
  const familyPath = `/families/${familyId}`

  function open(which: Exclude<OpenDialog, null>) {
    updateMember.reset()
    deleteMember.reset()
    setDialog(which)
  }

  function close() {
    setDialog(null)
  }

  return (
    <div className="flex flex-col gap-10">
      <PageHeader
        crumbs={[
          { label: 'Families', to: '/families' },
          { label: family.data.name, to: familyPath },
          { label: name },
        ]}
        title={name}
        leading={<MemberChip id={member.data.id} name={name} size="lg" />}
        actions={
          <>
            <Button
              variant="secondary"
              icon="pencil"
              onClick={() => {
                open('edit')
              }}
            >
              Edit details
            </Button>
            <Button
              variant="secondary"
              icon="trash"
              onClick={() => {
                open('delete')
              }}
            >
              Delete member
            </Button>
          </>
        }
      />

      <section aria-labelledby="details-heading">
        <h2 id="details-heading" className="sr-only">
          Details
        </h2>
        <dl className="grid max-w-2xl grid-cols-2 gap-x-8 gap-y-4 sm:grid-cols-3">
          <div>
            <dt className="text-muted">Sex</dt>
            <dd className="font-semibold">{sex === 'female' ? 'Female' : 'Male'}</dd>
          </div>
          <div>
            <dt className="text-muted">Date of birth</dt>
            <dd className="font-semibold">{dateOfBirth ? formatDate(dateOfBirth) : 'Not given'}</dd>
          </div>
          <div>
            <dt className="text-muted">Age</dt>
            <dd className="font-semibold">
              {dateOfBirth
                ? pluralize(ageOn(dateOfBirth), 'year', 'years')
                : 'Add a date of birth to show age'}
            </dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="reports-heading" className="flex flex-col gap-4">
        <h2 id="reports-heading" className="flex items-center gap-2 text-lg font-semibold">
          <Icon name="file" className="size-6 text-edta" />
          Reports
        </h2>
        <UploadReport familyId={familyId} memberId={member.data.id} memberName={name} />
        <ReportList familyId={familyId} memberId={member.data.id} />
      </section>

      <Dialog open={dialog === 'edit'} onClose={close} title={`Edit ${name}'s details`}>
        <MemberForm
          initial={member.data}
          submitLabel="Save changes"
          pendingLabel="Saving…"
          pending={updateMember.isPending}
          error={updateMember.error}
          onCancel={close}
          onSubmit={(input) => {
            updateMember.mutate(input, { onSuccess: close })
          }}
        />
      </Dialog>

      <ConfirmDialog
        open={dialog === 'delete'}
        onClose={close}
        title={`Delete ${name}?`}
        confirmLabel="Delete member"
        pendingLabel="Deleting…"
        pending={deleteMember.isPending}
        error={deleteMember.error}
        onConfirm={() => {
          deleteMember.mutate(undefined, {
            onSuccess: () => {
              void navigate(familyPath, { replace: true })
            },
          })
        }}
      >
        <p>
          This permanently deletes {name} from {family.data.name}, with all of their reports and
          results. It can't be undone.
        </p>
      </ConfirmDialog>
    </div>
  )
}
