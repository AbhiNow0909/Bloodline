import { useState, type SubmitEvent } from 'react'

import { ApiError } from '../lib/api'
import { focusFirstField } from '../lib/forms'
import { Button } from './Button'
import { ErrorState } from './States'
import { TextField } from './TextField'

interface FamilyNameFormProps {
  initialName?: string
  submitLabel: string
  pendingLabel: string
  pending: boolean
  error: Error | null
  onSubmit: (name: string) => void
  onCancel: () => void
}

export function FamilyNameForm({
  initialName = '',
  submitLabel,
  pendingLabel,
  pending,
  error,
  onSubmit,
  onCancel,
}: FamilyNameFormProps) {
  const [name, setName] = useState(initialName)
  const [localError, setLocalError] = useState<string | null>(null)
  const serverError = error instanceof ApiError ? error.fieldErrors.name : undefined

  function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) {
      setLocalError('Enter a name for the family.')
      focusFirstField(event.currentTarget, ['name'])
      return
    }
    setLocalError(null)
    onSubmit(trimmed)
  }

  return (
    <form noValidate onSubmit={handleSubmit} className="flex flex-col gap-5">
      <TextField
        label="Family name"
        hint="For example, Sharma family or Mum's side."
        name="name"
        value={name}
        onChange={(event) => {
          setName(event.target.value)
        }}
        maxLength={100}
        autoComplete="off"
        error={localError ?? serverError}
      />
      {error && !serverError && <ErrorState error={error} />}
      <div className="flex flex-wrap justify-end gap-3">
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending}>
          {pending ? pendingLabel : submitLabel}
        </Button>
      </div>
    </form>
  )
}
