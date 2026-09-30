import { useId, type InputHTMLAttributes } from 'react'

import { Button } from '../components/Button'
import { FieldError } from '../components/FieldError'
import { Icon } from '../components/Icon'
import type { MetricDefinition } from '../lib/types'
import { draftFlag, visibleWarnings, type DraftField, type DraftRow, type RowErrors } from './draft'
import { FlagLabel } from './FlagLabel'

interface CompactFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  error?: string
}

/** A labelled input sized for the review grid. */
function CompactField({ label, error, className = '', ...rest }: CompactFieldProps) {
  const id = useId()
  const errorId = `${id}-error`
  return (
    <div className={`flex min-w-0 flex-col gap-1 ${className}`}>
      <label htmlFor={id} className="text-sm text-muted">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        className="min-h-11 w-full rounded-lg border border-field bg-surface px-3 text-base text-ink aria-invalid:border-alert"
        {...rest}
      />
      {error && <FieldError id={errorId} message={error} />}
    </div>
  )
}

function DictionarySelect({
  row,
  dictionary,
  onChange,
}: {
  row: DraftRow
  dictionary: MetricDefinition[] | undefined
  onChange: (id: string | null) => void
}) {
  const id = useId()
  const byCategory = new Map<string, MetricDefinition[]>()
  for (const definition of dictionary ?? []) {
    const group = byCategory.get(definition.category) ?? []
    group.push(definition)
    byCategory.set(definition.category, group)
  }
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="text-sm text-muted">
        Matches the test
      </label>
      <select
        id={id}
        value={row.canonical_metric_id ?? ''}
        disabled={!dictionary}
        onChange={(event) => {
          onChange(event.target.value || null)
        }}
        className="min-h-11 w-full rounded-lg border border-field bg-surface px-2 text-base text-ink"
      >
        {!dictionary && row.canonical_metric_id !== null ? (
          <option value={row.canonical_metric_id}>Loading tests…</option>
        ) : (
          <option value="">Not in the list (keep the name as printed)</option>
        )}
        {[...byCategory].map(([category, definitions]) => (
          <optgroup key={category} label={category}>
            {definitions.map((definition) => (
              <option key={definition.id} value={definition.id}>
                {definition.canonical_name} ({definition.canonical_unit})
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  )
}

interface ReviewRowProps {
  row: DraftRow
  errors: RowErrors
  dictionary: MetricDefinition[] | undefined
  onChange: (changes: Partial<DraftRow>) => void
  onRemove: () => void
}

/** One extracted test: its printed details and the fields to correct. */
export function ReviewRow({ row, errors, dictionary, onChange, onRemove }: ReviewRowProps) {
  const name = row.raw_name.trim() || 'New test'
  const warnings = visibleWarnings(row)
  const field = (key: DraftField) => ({
    name: `${row.key}.${key}`,
    value: row[key],
    error: errors[key],
    onChange: (event: { target: { value: string } }) => {
      onChange({ [key]: event.target.value })
    },
  })

  if (!row.included) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed border-muted/50 px-4 py-3">
        <p className="min-w-0 text-muted">
          <span className="font-semibold text-ink">{name}</span>
          {row.value_text ? ` ${row.value_text} ${row.unit}` : ''}
          <span className="block text-sm">Left out: it will not be saved.</span>
        </p>
        <Button
          variant="quiet"
          icon="undo"
          onClick={() => {
            onChange({ included: true })
          }}
        >
          Include again
          <span className="sr-only">: {name}</span>
        </Button>
      </div>
    )
  }

  return (
    <fieldset
      className={`rounded-lg border bg-surface p-4 ${
        warnings.length > 0 ? 'border-edta border-l-4' : 'border-line'
      }`}
    >
      <legend className="sr-only">{name}</legend>

      <div className="grid gap-3 md:grid-cols-2">
        <CompactField label="Test name" {...field('raw_name')} maxLength={200} autoComplete="off" />
        <DictionarySelect
          row={row}
          dictionary={dictionary}
          onChange={(id) => {
            onChange({ canonical_metric_id: id })
          }}
        />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <CompactField label="Result" {...field('value_text')} maxLength={100} autoComplete="off" />
        <CompactField label="Unit" {...field('unit')} maxLength={50} autoComplete="off" />
        <CompactField label="Range from" {...field('low')} inputMode="decimal" autoComplete="off" />
        <CompactField label="Range to" {...field('high')} inputMode="decimal" autoComplete="off" />
      </div>

      <div className="mt-3 flex flex-col gap-0.5 text-sm text-muted">
        {row.reference_text && (
          <p className="break-words">
            Printed range: {row.reference_text}
            {row.reference_label && ` (used: ${row.reference_label})`}
          </p>
        )}
        {(row.panel ?? row.sample_type ?? row.method) && (
          <p className="break-words">
            {[row.panel, row.sample_type, row.method].filter(Boolean).join(', ')}
          </p>
        )}
        {row.added && <p>Added by you.</p>}
      </div>

      {warnings.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1">
          {warnings.map((warning) => (
            <li key={warning} className="flex items-start gap-1.5 text-sm font-semibold text-edta">
              <Icon name="alert" className="mt-0.5 size-4" />
              {warning}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4">
        <p className="text-sm">
          <span className="text-muted">Compared with the range: </span>
          <FlagLabel flag={draftFlag(row)} />
        </p>
        <Button
          variant="quiet"
          icon={row.added ? 'trash' : 'minus'}
          className="-mr-2"
          onClick={
            row.added
              ? onRemove
              : () => {
                  onChange({ included: false })
                }
          }
        >
          {row.added ? 'Remove' : 'Leave out'}
          <span className="sr-only">: {name}</span>
        </Button>
      </div>
    </fieldset>
  )
}
