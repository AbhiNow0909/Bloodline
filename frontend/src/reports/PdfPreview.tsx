import { Icon } from '../components/Icon'
import { ErrorState, LoadingState } from '../components/States'
import { useReportFileUrl } from '../lib/queries'

/** The original PDF, shown by the browser's own PDF viewer on wide screens. Phones often
 * cannot show a PDF inside a page, so the link (which opens the device's viewer) is always
 * there. The file is fetched with the session's token and stays in this browser. */
export function PdfPreview({ reportId }: { reportId: string }) {
  const file = useReportFileUrl(reportId)

  return (
    <section aria-labelledby="pdf-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <h2 id="pdf-heading" className="text-lg font-semibold">
          Original report
        </h2>
        {file.url && (
          <a
            href={file.url}
            target="_blank"
            rel="noopener"
            className="inline-flex min-h-11 items-center gap-1.5 font-semibold text-edta underline underline-offset-4"
          >
            Open the PDF
            <Icon name="external" className="size-4" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        )}
      </div>
      {file.isError && <ErrorState error={file.error} />}
      {!file.isError && !file.url && <LoadingState label="Loading the PDF…" />}
      {file.url && (
        <iframe
          title="Original report (PDF)"
          src={file.url}
          className="hidden h-[78vh] w-full rounded-lg border border-line bg-surface xl:block"
        />
      )}
    </section>
  )
}
