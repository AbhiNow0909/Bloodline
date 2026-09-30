import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { polling } from '../lib/queries'
import type { Reading } from '../lib/types'
import { fakeApi } from '../test/fakeApi'
import { renderApp } from '../test/render'
import { sampleReview } from '../test/reportData'
import { signIn } from '../test/session'

beforeEach(() => {
  signIn()
  polling.intervalMs = 20
})

afterEach(() => {
  polling.intervalMs = 2_000
})

function setup() {
  const api = fakeApi()
  const family = api.addFamily('Rao family')
  const amma = api.addMember(family.id, {
    display_name: 'Amma',
    sex: 'female',
    date_of_birth: '1968-03-01',
  })
  const memberPath = `/families/${family.id}/members/${amma.id}`
  const reportPath = (id: string) => `${memberPath}/reports/${id}`
  return { api, family, amma, memberPath, reportPath }
}

const pdfFile = (content = '%PDF-1.4 synthetic report', name = 'report.pdf') =>
  new File([content], name, { type: 'application/pdf' })

const reading = (fields: Partial<Reading>): Reading => ({
  patient_id: '',
  report_id: '',
  collected_at: '2026-09-28T02:35:00Z',
  canonical_metric_id: null,
  raw_name: '',
  value_text: '',
  value_numeric: null,
  unit: null,
  value_canonical: null,
  unit_canonical: null,
  reference_low: null,
  reference_high: null,
  reference_text: null,
  flag: 'unknown',
  ...fields,
})

/** The review card (fieldset) of a test, found by its name. */
const rowCard = (name: string) => screen.getByRole('group', { name })

describe('a member’s reports', () => {
  it('are listed with their status in words', async () => {
    const { api, amma, family } = setup()
    api.addReport(amma.id, { status: 'processing' })
    api.addReport(amma.id, { status: 'failed', failure_reason: 'The file is not a PDF.' })
    api.addReport(amma.id, {
      status: 'pending_review',
      lab_name: 'Example Labs',
      collected_at: '2026-09-28T02:35:00Z',
    })
    const saved = api.addReport(
      amma.id,
      { status: 'confirmed', lab_name: 'Example Labs', collected_at: '2026-03-02T20:00:00Z' },
      null,
      [reading({ flag: 'low' }), reading({ flag: 'normal' })],
    )
    renderApp(`/families/${family.id}/members/${amma.id}`)

    const list = await screen.findByRole('list', { name: 'Reports, newest first' })
    const items = within(list).getAllByRole('listitem')
    expect(items.map((item) => item.textContent)).toEqual([
      '2026Report of 3 Mar 2026Example Labs. 2 values, 1 outside the rangeSaved',
      'Report of 28 Sept 2026Example LabsNeeds your review',
      "Report uploaded 29 Sept 2026Couldn't be read",
      'Report uploaded 29 Sept 2026Being read',
    ])
    expect(screen.getByRole('link', { name: /Report of 3 Mar 2026/ })).toHaveAttribute(
      'href',
      `/families/${family.id}/members/${amma.id}/reports/${saved.id}`,
    )
  })
})

describe('uploading a report', () => {
  it('shows progress, then follows the report until it is ready to review', async () => {
    const { api, amma, memberPath } = setup()
    const release = api.holdUploads()
    const { user, router } = renderApp(memberPath)

    await user.upload(await screen.findByLabelText('Choose a PDF'), pdfFile())
    expect(await screen.findByText(/^Uploading report\.pdf: \d+%$/)).toBeVisible()
    release()

    expect(await screen.findByText('Reading the report')).toBeVisible()
    const [report] = api.reports.values()
    expect(router.state.location.pathname).toBe(`${memberPath}/reports/${report?.report.id ?? ''}`)
    const upload = api.calls.find((c) => c.method === 'POST')
    expect(upload).toMatchObject({
      path: `/patients/${amma.id}/reports`,
      contentType: 'application/pdf',
      authorization: expect.stringMatching(/^Bearer /) as unknown,
    })

    api.finishProcessing(report?.report.id ?? '')
    expect(await screen.findByRole('heading', { name: 'Values found' })).toBeVisible()
    expect(screen.getByText('Needs your review')).toBeVisible()
  })

  it('refuses a dropped file that is not a PDF, without uploading it', async () => {
    const { api, memberPath } = setup()
    renderApp(memberPath)
    const zone = (await screen.findByText('Add a lab report for Amma')).parentElement
    if (!zone) throw new Error('drop zone not found')
    const photo = new File(['jpg'], 'photo.jpg', { type: 'image/jpeg' })
    fireEvent.drop(zone, { dataTransfer: { files: [photo] } })

    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a PDF file.')
    expect(api.writes()).toHaveLength(0)
  })

  it('uploads a dropped PDF', async () => {
    const { api, memberPath } = setup()
    renderApp(memberPath)
    const zone = (await screen.findByText('Add a lab report for Amma')).parentElement
    if (!zone) throw new Error('drop zone not found')
    fireEvent.drop(zone, { dataTransfer: { files: [pdfFile()] } })

    expect(await screen.findByText('Reading the report')).toBeVisible()
    expect(api.reports.size).toBe(1)
  })

  it('links to the report already uploaded when the same PDF is sent again', async () => {
    const { api, amma, memberPath, reportPath } = setup()
    const first = api.addReport(amma.id, { status: 'confirmed' })
    const entry = api.reports.get(first.id)
    if (entry) entry.content = '%PDF-1.4 same bytes'
    const { user } = renderApp(memberPath)

    await user.upload(await screen.findByLabelText('Choose a PDF'), pdfFile('%PDF-1.4 same bytes'))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This report was already uploaded for this family member.',
    )
    expect(screen.getByRole('link', { name: 'Open the report already uploaded' })).toHaveAttribute(
      'href',
      reportPath(first.id),
    )
  })

  it('explains a dropped connection', async () => {
    const { api, memberPath } = setup()
    api.failUploads()
    const { user } = renderApp(memberPath)
    await user.upload(await screen.findByLabelText('Choose a PDF'), pdfFile())
    expect(await screen.findByRole('alert')).toHaveTextContent("The upload didn't finish.")
  })
})

describe('reviewing a report', () => {
  function pendingReport(
    review = sampleReview(),
    collectedAt: string | null = '2026-09-28T02:35:00Z',
  ) {
    const context = setup()
    const report = context.api.addReport(context.amma.id)
    context.api.finishProcessing(
      report.id,
      { lab_name: 'Example Labs', collected_at: collectedAt },
      review,
    )
    return { ...context, report, path: context.reportPath(report.id) }
  }

  it('shows each extracted value with its printed range, flag and warnings, next to the PDF', async () => {
    const { api, report, path } = pendingReport()
    renderApp(path)

    expect(await screen.findByRole('heading', { name: 'Values found' })).toBeVisible()
    expect(screen.getByText('4 tests found; 1 needs checking.')).toBeVisible()
    expect(screen.getByText('58 years, female')).toBeVisible()
    expect(screen.getByText('28 Sept 2026, 8:05 am')).toBeVisible()

    const hb = rowCard('HAEMOGLOBIN')
    expect(within(hb).getByLabelText('Result')).toHaveValue('13.5')
    expect(within(hb).getByLabelText('Range from')).toHaveValue('12.0')
    expect(within(hb).getByText('Printed range: Female: 12.0 - 15.0 (used: Female)')).toBeVisible()
    expect(within(hb).getByText('In range')).toBeVisible()
    expect(within(rowCard('FERRITIN')).getByText('Low')).toBeVisible()
    expect(within(rowCard('URINE GLUCOSE')).getByText('Not compared')).toBeVisible()
    expect(within(rowCard('COBALAMIN')).getByText(/Not in the metric dictionary yet/)).toBeVisible()
    expect(
      await within(hb).findByRole('option', { name: 'Hemoglobin (g/dL)', selected: true }),
    ).toBeInTheDocument()

    // The PDF is fetched with the session's token and shown from a local object URL.
    expect(await screen.findByTitle('Original report (PDF)')).toHaveAttribute(
      'src',
      expect.stringMatching(/^blob:/) as unknown,
    )
    expect(screen.getByRole('link', { name: /Open the PDF/ })).toHaveAttribute('target', '_blank')
    expect(api.calls.find((c) => c.path === `/reports/${report.id}/file`)?.authorization).toMatch(
      /^Bearer /,
    )
  })

  it('puts warnings about the person first', async () => {
    const review = {
      ...sampleReview(),
      warnings: ['The report is for a male patient, but this family member is recorded as female.'],
    }
    const { path } = pendingReport(review)
    renderApp(path)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Check this first')
    expect(alert).toHaveTextContent('The report is for a male patient')
  })

  it('saves the reviewed rows, with corrections, matches and left-out rows', async () => {
    const { api, report, path } = pendingReport()
    const { user } = renderApp(path)
    await screen.findByRole('heading', { name: 'Values found' })

    // Correct a misread value: the flag preview follows.
    const hbValue = within(rowCard('HAEMOGLOBIN')).getByLabelText('Result')
    await user.clear(hbValue)
    await user.type(hbValue, '16.2')
    expect(within(rowCard('HAEMOGLOBIN')).getByText('High')).toBeVisible()

    // Match the unknown test; its warning goes away.
    const cobalamin = rowCard('COBALAMIN')
    await user.selectOptions(
      await within(cobalamin).findByLabelText('Matches the test'),
      'Vitamin B12 (pg/mL)',
    )
    expect(within(cobalamin).queryByText(/Not in the metric dictionary/)).not.toBeInTheDocument()
    expect(screen.getByText('4 tests found.')).toBeVisible()

    // Leave one out (and it can be brought back).
    await user.click(within(rowCard('URINE GLUCOSE')).getByRole('button', { name: /Leave out/ }))
    expect(screen.getByText('Left out: it will not be saved.')).toBeVisible()
    expect(screen.getByText('3 values will be saved, 1 left out.')).toBeVisible()

    await user.click(screen.getByRole('button', { name: "Save to Amma's history" }))

    // The confirmation takes focus, which also brings it into view.
    expect(await screen.findByText("Saved 3 values to Amma's history.")).toHaveFocus()
    expect(api.confirmed(report.id)).toEqual({
      metrics: [
        expect.objectContaining({
          raw_name: 'HAEMOGLOBIN',
          value_text: '16.2',
          canonical_metric_id: 'metric-hb',
        }),
        expect.objectContaining({ raw_name: 'FERRITIN', value_text: '8.2', reference_low: '13' }),
        expect.objectContaining({ raw_name: 'COBALAMIN', canonical_metric_id: 'metric-b12' }),
      ],
    })
    // Now it shows the saved values instead of the form.
    const table = await screen.findByRole('table')
    expect(
      within(table).getByRole('rowheader', { name: 'HAEMOGLOBIN' }).closest('tr'),
    ).toHaveTextContent('HAEMOGLOBINResult: 16.2 g/dLRange: 12.0 – 15.0High')
    expect(screen.getByText(/They are not a diagnosis/)).toBeVisible()
    expect(screen.getByText('Saved')).toBeVisible()
  })

  it('asks for the collection date when the report did not print one', async () => {
    const { api, report, path } = pendingReport(sampleReview(), null)
    const { user } = renderApp(path)
    await screen.findByRole('heading', { name: 'Values found' })

    await user.click(screen.getByRole('button', { name: "Save to Amma's history" }))
    const date = screen.getByLabelText('Collection date (needed)')
    expect(date).toHaveFocus()
    expect(date).toHaveAccessibleDescription(
      'The date could not be read from the report. Enter the day the sample was collected. Enter the date the sample was collected.',
    )
    expect(api.writes()).toHaveLength(0)

    await user.type(date, '2026-09-01')
    await user.click(screen.getByRole('button', { name: "Save to Amma's history" }))
    expect(await screen.findByText("Saved 4 values to Amma's history.")).toBeVisible()
    expect(api.confirmed(report.id)?.collected_at).toBe('2026-09-01T12:00:00+05:30')
  })

  it('checks every row before saving and focuses the first problem', async () => {
    const { api, path } = pendingReport()
    const { user } = renderApp(path)
    await screen.findByRole('heading', { name: 'Values found' })

    const ferritin = rowCard('FERRITIN')
    await user.clear(within(ferritin).getByLabelText('Range to'))
    await user.type(within(ferritin).getByLabelText('Range to'), '10')
    await user.clear(within(rowCard('HAEMOGLOBIN')).getByLabelText('Result'))
    await user.click(screen.getByRole('button', { name: "Save to Amma's history" }))

    expect(screen.getByText('2 things need fixing before saving.')).toBeVisible()
    expect(within(rowCard('HAEMOGLOBIN')).getByLabelText('Result')).toHaveFocus()
    expect(within(rowCard('FERRITIN')).getByLabelText('Range to')).toHaveAccessibleDescription(
      'The end of the range must not be below its start.',
    )
    expect(api.writes()).toHaveLength(0)
  })

  it('can add a test the extraction missed', async () => {
    const { api, report, path } = pendingReport()
    const { user } = renderApp(path)
    await screen.findByRole('heading', { name: 'Values found' })

    await user.click(screen.getByRole('button', { name: 'Add a test that was missed' }))
    const added = rowCard('New test')
    expect(within(added).getByText('Added by you.')).toBeVisible()
    await user.type(within(added).getByLabelText('Test name'), 'Vitamin D')
    await user.type(within(rowCard('Vitamin D')).getByLabelText('Result'), '31')
    await user.type(within(rowCard('Vitamin D')).getByLabelText('Unit'), 'ng/mL')
    await user.click(screen.getByRole('button', { name: "Save to Amma's history" }))

    expect(await screen.findByText("Saved 5 values to Amma's history.")).toBeVisible()
    expect(api.confirmed(report.id)?.metrics.at(-1)).toEqual({
      raw_name: 'Vitamin D',
      canonical_metric_id: null,
      value_text: '31',
      unit: 'ng/mL',
      reference_low: null,
      reference_high: null,
      reference_text: null,
      sample_type: null,
      method: null,
    })
  })

  it('shows server field errors on the row they belong to', async () => {
    const { api, path } = pendingReport()
    api.override((call) =>
      call.path.endsWith('/confirm')
        ? {
            status: 422,
            body: {
              detail: [
                {
                  loc: ['body', 'metrics', 1, 'reference_low'],
                  msg: 'Decimal input should have no more than 18 digits',
                },
              ],
            },
          }
        : undefined,
    )
    const { user } = renderApp(path)
    await screen.findByRole('heading', { name: 'Values found' })
    await user.click(within(rowCard('URINE GLUCOSE')).getByRole('button', { name: /Leave out/ }))
    await user.click(screen.getByRole('button', { name: "Save to Amma's history" }))

    expect(
      await within(rowCard('FERRITIN')).findByText(
        'Decimal input should have no more than 18 digits',
      ),
    ).toBeVisible()
    expect(screen.getByText('Some details need fixing.')).toBeVisible()

    // Editing clears the server's messages: they were about the old values.
    await user.type(within(rowCard('FERRITIN')).getByLabelText('Range from'), '0')
    expect(screen.queryByText('Some details need fixing.')).not.toBeInTheDocument()
  })

  it('asks before leaving with unsaved corrections', async () => {
    const { path, memberPath } = pendingReport()
    const { user, router } = renderApp(path)
    await screen.findByRole('heading', { name: 'Values found' })
    await user.type(within(rowCard('HAEMOGLOBIN')).getByLabelText('Unit'), 'x')

    const breadcrumb = screen.getByRole('navigation', { name: 'Breadcrumb' })
    await user.click(within(breadcrumb).getByRole('link', { name: 'Amma' }))
    const dialog = await screen.findByRole('dialog', { name: 'Leave without saving?' })
    await user.click(within(dialog).getByRole('button', { name: 'Stay and keep editing' }))
    expect(router.state.location.pathname).toBe(path)
    expect(within(rowCard('HAEMOGLOBIN')).getByLabelText('Unit')).toHaveValue('g/dLx')

    await user.click(within(breadcrumb).getByRole('link', { name: 'Amma' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: 'Leave without saving',
      }),
    )
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(memberPath)
    })
  })
})

describe('other report states', () => {
  it('explains a failed report and can read it again', async () => {
    const { api, amma, reportPath } = setup()
    const report = api.addReport(amma.id, {
      status: 'failed',
      failure_reason: 'The AI service is busy. Try again in a minute.',
    })
    const { user } = renderApp(reportPath(report.id))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "This report couldn't be readThe AI service is busy. Try again in a minute.",
    )
    await user.click(screen.getByRole('button', { name: 'Try reading it again' }))
    expect(await screen.findByText('Reading the report')).toBeVisible()
    api.finishProcessing(report.id)
    expect(await screen.findByRole('heading', { name: 'Values found' })).toBeVisible()
  })

  it('deletes a report after confirming, even with unsaved corrections', async () => {
    const { api, amma, reportPath, memberPath } = setup()
    const report = api.addReport(amma.id)
    api.finishProcessing(report.id)
    const { user, router } = renderApp(reportPath(report.id))
    await screen.findByRole('heading', { name: 'Values found' })
    await user.type(within(rowCard('HAEMOGLOBIN')).getByLabelText('Unit'), 'x')

    await user.click(screen.getByRole('button', { name: 'Delete report' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete this report?' })
    expect(dialog).toHaveTextContent(
      'This permanently deletes the report, its PDF and any values saved from it.',
    )
    await user.click(within(dialog).getByRole('button', { name: 'Delete report' }))

    expect(await screen.findByText('No reports yet.')).toBeVisible()
    expect(router.state.location.pathname).toBe(memberPath)
    expect(api.reports.size).toBe(0)
    expect(screen.queryByRole('dialog', { name: 'Leave without saving?' })).not.toBeInTheDocument()
  })

  it('is "not found" under another member\'s address', async () => {
    const { api, amma, family } = setup()
    const appa = api.addMember(family.id, {
      display_name: 'Appa',
      sex: 'male',
      date_of_birth: null,
    })
    const report = api.addReport(amma.id)
    renderApp(`/families/${family.id}/members/${appa.id}/reports/${report.id}`)
    expect(await screen.findByRole('heading', { name: "This report can't be found" })).toBeVisible()
  })
})
