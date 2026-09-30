import type { ReactNode } from 'react'

export interface Column<Row> {
  header: string
  /** Shown before the value on phones, where the header row is hidden (e.g. "Range"). */
  mobileLabel?: string
  /** Width on wider screens (with `fixed`), e.g. "w-1/5". */
  width?: string
  cell: (row: Row) => ReactNode
}

interface ResponsiveTableProps<Row> {
  /** The first column: the row's name, read out as the header of each row. */
  rowHeader: Column<Row>
  columns: Column<Row>[]
  rows: Row[]
  rowKey: (row: Row, index: number) => string
  /** Names the table for screen readers. */
  label: string
  /** Use the columns' widths, so tables shown one after another line up. */
  fixed?: boolean
}

/** A real table on wider screens. On phones each row stacks, with its own labels, so no
 * column (such as Low/High) is ever scrolled out of view. */
export function ResponsiveTable<Row>({
  rowHeader,
  columns,
  rows,
  rowKey,
  label,
  fixed = false,
}: ResponsiveTableProps<Row>) {
  return (
    <div className="rounded-lg border border-line bg-surface">
      <table
        aria-label={label}
        className={`w-full border-collapse text-left max-sm:block ${fixed ? 'sm:table-fixed' : ''}`}
      >
        <thead className="border-b border-line text-sm text-muted max-sm:sr-only">
          <tr>
            {[rowHeader, ...columns].map((column) => (
              <th
                key={column.header}
                scope="col"
                className={`px-4 py-3 font-semibold ${column.width ?? ''}`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="max-sm:block">
          {rows.map((row, index) => (
            <tr
              key={rowKey(row, index)}
              className="border-b border-line last:border-b-0 max-sm:flex max-sm:flex-col max-sm:gap-0.5 max-sm:px-4 max-sm:py-3"
            >
              <th scope="row" className="px-4 py-3 font-semibold break-words max-sm:p-0">
                {rowHeader.cell(row)}
              </th>
              {columns.map((column) => (
                <td key={column.header} className="px-4 py-3 max-sm:p-0">
                  {column.mobileLabel && (
                    <span className="text-muted sm:hidden">{column.mobileLabel}: </span>
                  )}
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
