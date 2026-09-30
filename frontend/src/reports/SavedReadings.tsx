import { ResponsiveTable } from '../components/ResponsiveTable'
import { ErrorState, LoadingState } from '../components/States'
import { useReadings } from '../lib/queries'
import { rangeText } from '../lib/values'
import { FlagLabel } from './FlagLabel'
import { NotDiagnosis } from './NotDiagnosis'

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
      <ResponsiveTable
        label="Saved values"
        rows={readings.data}
        rowKey={(reading, index) => `${String(index)}-${reading.raw_name}`}
        rowHeader={{ header: 'Test', cell: (reading) => reading.raw_name }}
        columns={[
          {
            header: 'Result',
            mobileLabel: 'Result',
            cell: (reading) => `${reading.value_text ?? ''} ${reading.unit ?? ''}`.trim(),
          },
          { header: 'Reference range', mobileLabel: 'Range', cell: rangeText },
          {
            header: 'Compared with the range',
            cell: (reading) => <FlagLabel flag={reading.flag} />,
          },
        ]}
      />
      <NotDiagnosis />
    </section>
  )
}
