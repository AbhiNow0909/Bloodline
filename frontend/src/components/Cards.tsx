import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { Icon } from './Icon'

/* The file-system metaphor made literal: a family is a folder with a tab, a member is a
   file with a folded corner. Focus rings sit on the outer element, which is never clipped. */

const FOLDER_BODY =
  'block rounded-lg rounded-tl-none border bg-surface px-5 pb-5 pt-4 transition-colors'
const FOLDER_TAB = 'relative z-10 -mb-px block h-4 w-28 rounded-t-lg border border-b-0 bg-surface'

export function FolderLink({ to, name, detail }: { to: string; name: string; detail: string }) {
  return (
    <Link to={to} className="group block rounded-lg">
      <span aria-hidden="true" className={`${FOLDER_TAB} border-line group-hover:border-edta`} />
      <span className={`${FOLDER_BODY} border-line group-hover:border-edta`}>
        <span className="flex items-center gap-2 text-lg font-semibold">
          <Icon name="folder" className="size-6 text-edta" />
          {name}
        </span>
        <span className="mt-1 block text-muted">{detail}</span>
      </span>
    </Link>
  )
}

export function NewFolderButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="group block w-full rounded-lg text-left">
      <span
        aria-hidden="true"
        className={`${FOLDER_TAB} border-dashed border-muted/50 bg-transparent group-hover:border-edta`}
      />
      <span
        className={`${FOLDER_BODY} border-dashed border-muted/50 bg-transparent text-edta group-hover:border-edta group-hover:bg-surface`}
      >
        <span className="flex items-center gap-2 text-lg font-semibold">
          <Icon name="plus" className="size-6" />
          {label}
        </span>
        <span className="mt-1 block text-muted">A folder for a group of people</span>
      </span>
    </button>
  )
}

const FILE_BODY =
  'relative flex items-center gap-4 rounded-lg border bg-surface p-4 pr-10 transition-colors ' +
  '[clip-path:polygon(0_0,calc(100%-1.1rem)_0,100%_1.1rem,100%_100%,0_100%)]'
const DOG_EAR =
  'absolute right-0 top-0 size-[1.1rem] rounded-bl-sm bg-line [clip-path:polygon(0_0,100%_100%,0_100%)]'

export function FileLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="group block rounded-lg">
      <span className={`${FILE_BODY} border-line group-hover:border-edta`}>
        {children}
        <span aria-hidden="true" className={`${DOG_EAR} group-hover:bg-edta`} />
      </span>
    </Link>
  )
}

export function NewFileButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="group block w-full rounded-lg text-left">
      <span
        className={`${FILE_BODY} min-h-20 border-dashed border-muted/50 bg-transparent font-semibold text-edta group-hover:border-edta group-hover:bg-surface`}
      >
        <Icon name="plus" className="size-6" />
        {label}
        <span aria-hidden="true" className={`${DOG_EAR} group-hover:bg-edta`} />
      </span>
    </button>
  )
}
