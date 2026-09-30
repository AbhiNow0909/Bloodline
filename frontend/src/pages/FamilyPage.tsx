import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'

import { Button } from '../components/Button'
import { FileLink, NewFileButton } from '../components/Cards'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Dialog } from '../components/Dialog'
import { FamilyNameForm } from '../components/FamilyNameForm'
import { MemberChip } from '../components/MemberChip'
import { MemberForm } from '../components/MemberForm'
import { PageHeader } from '../components/PageHeader'
import { ErrorState, LoadingState } from '../components/States'
import { ApiError } from '../lib/api'
import { describeMember, pluralize } from '../lib/format'
import {
  useAddMember,
  useDeleteFamily,
  useFamily,
  useMembers,
  useRenameFamily,
} from '../lib/queries'
import { NotFound } from './NotFoundPage'

type OpenDialog = 'add' | 'rename' | 'delete' | null

export function FamilyPage() {
  const { familyId = '' } = useParams()
  const family = useFamily(familyId)
  const members = useMembers(familyId)
  const addMember = useAddMember(familyId)
  const renameFamily = useRenameFamily(familyId)
  const deleteFamily = useDeleteFamily(familyId)
  const navigate = useNavigate()
  const [dialog, setDialog] = useState<OpenDialog>(null)

  const error = family.error ?? members.error
  if (error instanceof ApiError && error.status === 404) {
    return <NotFound what="family" />
  }
  if (error) return <ErrorState error={error} />
  if (!family.data || !members.data) return <LoadingState />

  const name = family.data.name
  const count = members.data.length

  function open(which: Exclude<OpenDialog, null>) {
    addMember.reset()
    renameFamily.reset()
    deleteFamily.reset()
    setDialog(which)
  }

  function close() {
    setDialog(null)
  }

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        crumbs={[{ label: 'Families', to: '/families' }, { label: name }]}
        title={name}
        subtitle={pluralize(count, 'member', 'members')}
        actions={
          <>
            <Button
              variant="secondary"
              icon="pencil"
              onClick={() => {
                open('rename')
              }}
            >
              Rename
            </Button>
            <Button
              variant="secondary"
              icon="trash"
              onClick={() => {
                open('delete')
              }}
            >
              Delete family
            </Button>
          </>
        }
      />

      <section aria-labelledby="members-heading" className="flex flex-col gap-4">
        <h2 id="members-heading" className="text-lg font-semibold">
          Family members
        </h2>
        {count === 0 && (
          <p className="max-w-prose">
            No one is in this family yet. Add the people whose lab reports you want to keep here.
          </p>
        )}
        <ul className="grid gap-4 sm:grid-cols-2">
          {members.data.map((member) => (
            <li key={member.id}>
              <FileLink to={`/families/${familyId}/members/${member.id}`}>
                <MemberChip id={member.id} name={member.display_name} />
                <span className="min-w-0">
                  <span className="block font-semibold break-words">{member.display_name}</span>
                  <span className="block text-muted">
                    {describeMember(member.sex, member.date_of_birth)}
                  </span>
                </span>
              </FileLink>
            </li>
          ))}
          <li>
            <NewFileButton
              label="Add family member"
              onClick={() => {
                open('add')
              }}
            />
          </li>
        </ul>
      </section>

      <Dialog open={dialog === 'add'} onClose={close} title={`Add someone to ${name}`}>
        <MemberForm
          submitLabel="Add member"
          pendingLabel="Adding…"
          pending={addMember.isPending}
          error={addMember.error}
          onCancel={close}
          onSubmit={(input) => {
            addMember.mutate(input, { onSuccess: close })
          }}
        />
      </Dialog>

      <Dialog open={dialog === 'rename'} onClose={close} title="Rename family">
        <FamilyNameForm
          initialName={name}
          submitLabel="Save name"
          pendingLabel="Saving…"
          pending={renameFamily.isPending}
          error={renameFamily.error}
          onCancel={close}
          onSubmit={(newName) => {
            renameFamily.mutate(newName, { onSuccess: close })
          }}
        />
      </Dialog>

      <ConfirmDialog
        open={dialog === 'delete'}
        onClose={close}
        title={`Delete ${name}?`}
        confirmLabel="Delete family"
        pendingLabel="Deleting…"
        pending={deleteFamily.isPending}
        error={deleteFamily.error}
        onConfirm={() => {
          deleteFamily.mutate(undefined, {
            onSuccess: () => {
              void navigate('/families', { replace: true })
            },
          })
        }}
      >
        <p>
          This permanently deletes the family
          {count > 0 ? `, its ${pluralize(count, 'member', 'members')}` : ''} and all of their
          reports and results. It can't be undone.
        </p>
      </ConfirmDialog>
    </div>
  )
}
