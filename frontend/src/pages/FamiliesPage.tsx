import { useState } from 'react'
import { useNavigate } from 'react-router'

import { FolderLink, NewFolderButton } from '../components/Cards'
import { Dialog } from '../components/Dialog'
import { FamilyNameForm } from '../components/FamilyNameForm'
import { PageHeader } from '../components/PageHeader'
import { ErrorState, LoadingState } from '../components/States'
import { pluralize } from '../lib/format'
import { useCreateFamily, useFamilies } from '../lib/queries'

export function FamiliesPage() {
  const families = useFamilies()
  const createFamily = useCreateFamily()
  const navigate = useNavigate()
  const [creating, setCreating] = useState(false)

  function openCreate() {
    createFamily.reset()
    setCreating(true)
  }

  function close() {
    setCreating(false)
  }

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Families"
        subtitle="Each family is a folder for the people whose lab reports you keep."
      />

      {families.isPending && <LoadingState label="Loading your families…" />}
      {families.isError && <ErrorState error={families.error} />}
      {families.data && (
        <>
          {families.data.length === 0 && (
            <p className="max-w-prose">
              You have no families yet. Create one, then add the people in it: yourself, your
              parents, anyone whose reports you look after.
            </p>
          )}
          <ul className="grid gap-x-5 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
            {families.data.map((family) => (
              <li key={family.id}>
                <FolderLink
                  to={`/families/${family.id}`}
                  name={family.name}
                  detail={pluralize(family.patient_count, 'member', 'members')}
                />
              </li>
            ))}
            <li>
              <NewFolderButton label="New family" onClick={openCreate} />
            </li>
          </ul>
        </>
      )}

      <Dialog open={creating} onClose={close} title="New family">
        <FamilyNameForm
          submitLabel="Create family"
          pendingLabel="Creating…"
          pending={createFamily.isPending}
          error={createFamily.error}
          onCancel={close}
          onSubmit={(name) => {
            createFamily.mutate(name, {
              onSuccess: (family) => {
                void navigate(`/families/${family.id}`)
              },
            })
          }}
        />
      </Dialog>
    </div>
  )
}
