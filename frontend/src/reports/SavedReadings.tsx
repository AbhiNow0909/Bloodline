import { ErrorState, LoadingState } from '../components/States'
import { useReadings } from '../lib/queries'
import type { Reading } from '../lib/types'
import { formatRange } from '../lib/values'
import { FlagLabel } from './FlagLabel'

function rangeText(reading: Reading): string {
  return formatRange(reading.reference_low, reading.reference_high) ?? reading.reference_text ?? '–'
}

/** The values saved from one confirmed report. */
export function SavedReadings({ reportId }: { reportId: string }) {
  const readings = useReadings(reportId, true)

  if (readings.isPending) return <LoadingState label="Loading the saved values…" />
  if (readings.isError) return <ErrorState error={readings.error} />

  return (
    <section aria-labelledby="values-heading" className="flex flex-col gap-3">
      <h2 id="values-heading" className="text-lg font-semibold">
        Saved values
      </h2>
      {/* A table on wider screens; on phones each row stacks, with its own labels, so the
          Low/High column is never scrolled out of view. */}
      <div className="rounded-lg border border-line bg-surface">
        <table className="w-full border-collapse text-left max-sm:block">
          <thead className="border-b border-line text-sm text-muted max-sm:sr-only">
            <tr>
              <th scope="col" className="px-4 py-3 font-semibold">
                Test
              </th>
              <th scope="col" className="px-4 py-3 font-semibold">
                Result
              </th>
              <th scope="col" className="px-4 py-3 font-semibold">
                Reference range
              </th>
              <th scope="col" className="px-4 py-3 font-semibold">
                Compared with the range
              </th>
            </tr>
          </thead>
          <tbody className="max-sm:block">
            {readings.data.map((reading, index) => (
              <tr
                key={`${String(index)}-${reading.raw_name}`}
                className="border-b border-line last:border-b-0 max-sm:flex max-sm:flex-col max-sm:gap-0.5 max-sm:px-4 max-sm:py-3"
              >
                <th scope="row" className="px-4 py-3 font-semibold break-words max-sm:p-0">
                  {reading.raw_name}
                </th>
                <td className="px-4 py-3 max-sm:p-0">
                  <span className="text-muted sm:hidden">Result: </span>
                  {reading.value_text} {reading.unit}
                </td>
                <td className="px-4 py-3 max-sm:p-0">
                  <span className="text-muted sm:hidden">Range: </span>
                  {rangeText(reading)}
                </td>
                <td className="px-4 py-3 max-sm:p-0">
                  <FlagLabel flag={reading.flag} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="max-w-prose text-sm text-muted">
        Low and High only mean the value is outside the range printed by the lab. They are not a
        diagnosis; talk to your doctor about what your results mean.
      </p>
    </section>
  )
}
