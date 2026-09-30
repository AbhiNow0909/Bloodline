import { Icon } from './Icon'

/** An error next to a field or form: an icon and words, never colour alone. */
export function FieldError({ id, message }: { id?: string; message: string }) {
  return (
    <p id={id} className="flex items-start gap-1.5 text-sm font-semibold text-alert">
      <Icon name="alert" className="mt-0.5 size-4" />
      {message}
    </p>
  )
}
