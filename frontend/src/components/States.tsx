import type { ReactNode } from 'react'

import { errorMessage } from '../lib/api'
import { Icon } from './Icon'

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <p role="status" className="py-8 text-muted">
      {label}
    </p>
  )
}

export function ErrorState({ error, className = '' }: { error: unknown; className?: string }) {
  return (
    <div
      role="alert"
      className={`flex items-start gap-2 rounded-lg border border-alert/30 bg-alert-soft px-4 py-3 font-semibold text-alert ${className}`}
    >
      <Icon name="alert" className="mt-1 size-5" />
      <p>{errorMessage(error)}</p>
    </div>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line px-5 py-6 text-muted">
      {children}
    </div>
  )
}
