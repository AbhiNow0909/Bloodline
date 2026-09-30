import { Icon, type IconName } from '../components/Icon'
import type { ReportStatus } from '../lib/types'

const STATUS: Record<ReportStatus, { label: string; icon: IconName; className: string }> = {
  processing: { label: 'Being read', icon: 'clock', className: 'bg-paper text-ink' },
  pending_review: {
    label: 'Needs your review',
    icon: 'pencil',
    className: 'bg-edta-soft text-edta',
  },
  failed: { label: "Couldn't be read", icon: 'alert', className: 'bg-alert-soft text-alert' },
  confirmed: { label: 'Saved', icon: 'check', className: 'bg-paper text-ink' },
}

/** A report's status in words with an icon (never colour alone). */
export function StatusBadge({ status }: { status: ReportStatus }) {
  const { label, icon, className } = STATUS[status]
  return (
    <span
      className={`inline-flex w-fit shrink-0 items-center gap-1.5 rounded-full px-3 py-0.5 text-sm font-semibold ${className}`}
    >
      <Icon name={icon} className="size-4" />
      {label}
    </span>
  )
}
