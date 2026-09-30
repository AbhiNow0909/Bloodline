import { useId, useState, type DragEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { Icon } from '../components/Icon'
import { ErrorState } from '../components/States'
import { ApiError, MAX_UPLOAD_MB } from '../lib/api'
import { useUploadReport } from '../lib/queries'
import { reportPath } from './labels'
import { duplicateOf, fileProblem } from './upload'

export function UploadReport({
  familyId,
  memberId,
  memberName,
}: {
  familyId: string
  memberId: string
  memberName: string
}) {
  const upload = useUploadReport(memberId)
  const navigate = useNavigate()
  const [problem, setProblem] = useState<string | null>(null)
  const [fileName, setFileName] = useState('')
  const [dragging, setDragging] = useState(false)
  const statusId = useId()

  function start(file: File | undefined) {
    if (!file || upload.isPending) return
    upload.reset()
    const found = fileProblem(file)
    setProblem(found)
    if (found) return
    setFileName(file.name)
    upload.mutate(file, {
      onSuccess: (report) => {
        void navigate(reportPath(familyId, report))
      },
    })
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    start(event.dataTransfer.files[0])
  }

  const duplicateId = duplicateOf(upload.error)
  const percent = Math.round(upload.progress * 100)

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => {
        setDragging(false)
      }}
      onDrop={onDrop}
      className={`rounded-lg border-2 border-dashed p-5 transition-colors sm:p-6 ${
        dragging ? 'border-edta bg-edta-soft' : 'border-muted/50 bg-surface'
      }`}
    >
      <p className="font-semibold">Add a lab report for {memberName}</p>
      <p className="mt-1 max-w-prose text-muted">
        A PDF from the lab, up to {MAX_UPLOAD_MB} MB. You will check the values it finds before
        anything is saved.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
        <label
          className={`inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-lg bg-edta px-4 py-2 font-semibold text-white has-focus-visible:outline-3 has-focus-visible:outline-offset-3 has-focus-visible:outline-edta hover:bg-[#3e3378] ${
            upload.isPending ? 'pointer-events-none opacity-60' : ''
          }`}
        >
          <Icon name="upload" />
          Choose a PDF
          <input
            type="file"
            accept="application/pdf,.pdf"
            disabled={upload.isPending}
            aria-describedby={statusId}
            className="sr-only"
            onChange={(event) => {
              start(event.target.files?.[0])
              event.target.value = '' // choosing the same file again still triggers a change
            }}
          />
        </label>
        <span className="hidden text-muted sm:inline">or drop it here</span>
      </div>

      <div id={statusId} className="mt-4 empty:hidden">
        {upload.isPending && (
          <div role="status" className="flex flex-col gap-2">
            <p className="break-words">
              {percent < 100
                ? `Uploading ${fileName}: ${String(percent)}%`
                : `Uploaded ${fileName}. Starting to read it…`}
            </p>
            <div
              aria-hidden="true"
              className="h-2 w-full max-w-md overflow-hidden rounded-full bg-edta-soft"
            >
              <div
                className="h-full rounded-full bg-edta"
                style={{ width: `${String(percent)}%` }}
              />
            </div>
          </div>
        )}
        {problem && <ErrorState error={new ApiError(0, problem)} />}
        {upload.error && (
          <div className="flex flex-col gap-2">
            <ErrorState error={upload.error} />
            {duplicateId && (
              <Link
                to={reportPath(familyId, { id: duplicateId, patient_id: memberId })}
                className="w-fit font-semibold text-edta underline underline-offset-4"
              >
                Open the report already uploaded
              </Link>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
