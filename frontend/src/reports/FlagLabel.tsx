import { Icon, type IconName } from '../components/Icon'
import type { MetricFlag } from '../lib/types'

const FLAGS: Record<MetricFlag, { label: string; icon: IconName; className: string }> = {
  low: { label: 'Low', icon: 'arrowDown', className: 'font-semibold text-alert' },
  high: { label: 'High', icon: 'arrowUp', className: 'font-semibold text-alert' },
  normal: { label: 'In range', icon: 'check', className: 'text-muted' },
  unknown: { label: 'Not compared', icon: 'minus', className: 'text-muted' },
}

/** Where a value sits against its reference range, in words with an icon. "Low" and "High"
 * only mean outside the lab's printed range; they are not a diagnosis. */
export function FlagLabel({ flag }: { flag: MetricFlag }) {
  const { label, icon, className } = FLAGS[flag]
  return (
    <span className={`inline-flex items-center gap-1 ${className}`}>
      <Icon name={icon} className="size-4" />
      {label}
    </span>
  )
}
