import type { ButtonHTMLAttributes } from 'react'

import { Icon, type IconName } from './Icon'

type Variant = 'primary' | 'secondary' | 'danger' | 'quiet'

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-edta text-white hover:bg-[#3e3378]',
  secondary: 'border border-line bg-surface text-ink hover:border-edta hover:text-edta',
  danger: 'bg-alert text-white hover:bg-[#8a1f24]',
  quiet: 'text-edta hover:bg-edta-soft',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  icon?: IconName
}

export function Button({
  variant = 'primary',
  icon,
  className = '',
  type = 'button',
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {icon && <Icon name={icon} />}
      {children}
    </button>
  )
}
