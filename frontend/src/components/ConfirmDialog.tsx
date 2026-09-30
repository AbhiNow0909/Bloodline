import type { ReactNode } from 'react'

import { Button } from './Button'
import { Dialog } from './Dialog'
import { ErrorState } from './States'

interface ConfirmDialogProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  confirmLabel: string
  pendingLabel: string
  onConfirm: () => void
  pending: boolean
  error: unknown
}

/** Confirms a destructive action. The consequence is spelled out in `children`, and the
 * button names the action ("Delete family"), not "OK". */
export function ConfirmDialog({
  open,
  onClose,
  title,
  children,
  confirmLabel,
  pendingLabel,
  onConfirm,
  pending,
  error,
}: ConfirmDialogProps) {
  return (
    <Dialog open={open} onClose={onClose} title={title}>
      <div className="max-w-prose text-base">{children}</div>
      {error !== null && <ErrorState error={error} className="mt-4" />}
      <div className="mt-6 flex flex-wrap justify-end gap-3">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="danger" icon="trash" onClick={onConfirm} disabled={pending}>
          {pending ? pendingLabel : confirmLabel}
        </Button>
      </div>
    </Dialog>
  )
}
