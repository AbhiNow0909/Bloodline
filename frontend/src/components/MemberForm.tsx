import { useId, useState, type SubmitEvent } from 'react'

import { ApiError } from '../lib/api'
import { focusFirstField } from '../lib/forms'
import type { Member, MemberInput, Sex } from '../lib/types'
import { Button } from './Button'
import { FieldError } from './FieldError'
import { ErrorState } from './States'
import { TextField } from './TextField'

interface MemberFormProps {
  initial?: Member
  submitLabel: string
  pendingLabel: string
  pending: boolean
  error: Error | null
  onSubmit: (input: MemberInput) => void
  onCancel: () => void
}

type Errors = Partial<Record<keyof MemberInput, string>>

/** Today as "YYYY-MM-DD" in the user's own time zone (the latest allowed date of birth). */
function todayIso(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

function validate(name: string, sex: Sex | null, dateOfBirth: string): Errors {
  const errors: Errors = {}
  if (!name.trim()) errors.display_name = 'Enter a name.'
  if (sex === null) errors.sex = 'Choose female or male.'
  if (dateOfBirth && dateOfBirth >= todayIso()) {
    errors.date_of_birth = 'Enter a date of birth before today.'
  }
  return errors
}

export function MemberForm({
  initial,
  submitLabel,
  pendingLabel,
  pending,
  error,
  onSubmit,
  onCancel,
}: MemberFormProps) {
  const [name, setName] = useState(initial?.display_name ?? '')
  const [sex, setSex] = useState<Sex | null>(initial?.sex ?? null)
  const [dateOfBirth, setDateOfBirth] = useState(initial?.date_of_birth ?? '')
  const [localErrors, setLocalErrors] = useState<Errors>({})
  const sexHintId = useId()
  const sexErrorId = useId()

  const serverErrors = error instanceof ApiError ? error.fieldErrors : {}
  const errors: Errors = {
    display_name: localErrors.display_name ?? serverErrors.display_name,
    sex: localErrors.sex ?? serverErrors.sex,
    date_of_birth: localErrors.date_of_birth ?? serverErrors.date_of_birth,
  }
  // A server error about a field shows next to it; anything else shows below the form.
  const shownOnField = Boolean(
    serverErrors.display_name ?? serverErrors.sex ?? serverErrors.date_of_birth,
  )

  function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    const found = validate(name, sex, dateOfBirth)
    setLocalErrors(found)
    if (Object.keys(found).length > 0 || sex === null) {
      focusFirstField(event.currentTarget, Object.keys(found))
      return
    }
    onSubmit({ display_name: name.trim(), sex, date_of_birth: dateOfBirth || null })
  }

  return (
    <form noValidate onSubmit={handleSubmit} className="flex flex-col gap-6">
      <TextField
        label="Name"
        hint="What you call them, like Mum or Ravi. Only you see it, and it is never sent to the AI."
        value={name}
        onChange={(event) => {
          setName(event.target.value)
        }}
        name="display_name"
        maxLength={100}
        autoComplete="off"
        error={errors.display_name}
      />

      <fieldset
        aria-describedby={[sexHintId, errors.sex ? sexErrorId : null].filter(Boolean).join(' ')}
        className="flex flex-col gap-1.5"
      >
        <legend className="mb-1.5 font-semibold">Sex</legend>
        <p id={sexHintId} className="text-sm text-muted">
          Lab reports print different reference ranges for women and men.
        </p>
        <div className="mt-1 flex flex-wrap gap-3">
          {(['female', 'male'] as const).map((option) => (
            <label
              key={option}
              className="flex min-h-12 cursor-pointer items-center gap-3 rounded-lg border border-line bg-surface px-4 has-checked:border-edta has-checked:bg-edta-soft"
            >
              <input
                type="radio"
                name="sex"
                value={option}
                checked={sex === option}
                onChange={() => {
                  setSex(option)
                }}
                className="size-5 accent-edta"
              />
              {option === 'female' ? 'Female' : 'Male'}
            </label>
          ))}
        </div>
        {errors.sex && <FieldError id={sexErrorId} message={errors.sex} />}
      </fieldset>

      <TextField
        label="Date of birth (optional)"
        hint="Used to show their age."
        type="date"
        name="date_of_birth"
        value={dateOfBirth}
        max={todayIso()}
        onChange={(event) => {
          setDateOfBirth(event.target.value)
        }}
        error={errors.date_of_birth}
        className="max-w-60"
      />

      {error && !shownOnField && <ErrorState error={error} />}
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
