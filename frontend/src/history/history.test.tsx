import { screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import type { Reading } from '../lib/types'
import { fakeApi } from '../test/fakeApi'
import { renderApp } from '../test/render'
import { signIn } from '../test/session'

beforeEach(() => {
  signIn()
})

const reading = (fields: Partial<Reading>): Reading => ({
  patient_id: '',
  report_id: '',
  collected_at: '2025-03-03T02:35:00Z',
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

const ferritin = (collectedAt: string, value: string, flag: Reading['flag']) =>
  reading({
    collected_at: collectedAt,
    canonical_metric_id: 'metric-ferritin',
    raw_name: 'FERRITIN',
    value_text: value,
    value_numeric: value,
    unit: 'ng/mL',
    value_canonical: value,
    unit_canonical: 'ng/mL',
    reference_low: '4.63',
    reference_high: '204.00',
    reference_text: 'Women: 4.63 - 204.00 ng/ml',
    flag,
  })

function setup() {
  const api = fakeApi()
  const family = api.addFamily('Rao family')
  const amma = api.addMember(family.id, {
    display_name: 'Amma',
    sex: 'female',
    date_of_birth: null,
  })
  const memberPath = `/families/${family.id}/members/${amma.id}`
  /** A confirmed report with these readings (their ids are filled in). */
  const saved = (memberId: string, collectedAt: string, readings: Reading[]) => {
    const report = api.addReport(memberId, { status: 'confirmed', collected_at: collectedAt })
    const entry = api.reports.get(report.id)
    if (entry) {
      entry.readings = readings.map((r) => ({
        ...r,
        patient_id: memberId,
        report_id: report.id,
        collected_at: collectedAt,
      }))
    }
    return report
  }
  return { api, family, amma, memberPath, saved }
}

describe('a member’s latest results', () => {
  it('say where results will appear before any are saved', async () => {
    const { memberPath } = setup()
    renderApp(memberPath)
    expect(
      await screen.findByText(
        'No results yet. They appear here once a report is reviewed and saved.',
      ),
    ).toBeVisible()
  })

  it('list what is outside the range first, then every test by category', async () => {
    const { amma, memberPath, saved } = setup()
    saved(amma.id, '2024-03-01T04:00:00Z', [ferritin('', '60.1', 'normal')])
    saved(amma.id, '2025-03-03T02:35:00Z', [
      ferritin('', '3.9', 'low'),
      reading({
        canonical_metric_id: 'metric-hb',
        raw_name: 'HAEMOGLOBIN',
        value_text: '13.5',
        unit: 'g/dL',
        reference_low: '12.0',
        reference_high: '15.0',
        flag: 'normal',
      }),
      reading({ raw_name: 'URINE GLUCOSE', value_text: 'Negative' }),
    ])
    renderApp(memberPath)

    const attention = await screen.findByRole('region', { name: 'What stands out' })
    expect(
      within(attention)
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual([
      "LowFerritinMoved below the lab's range" +
        "Latest, 3 Mar 2025: 3.9 ng/mL (lab's range 4.63 – 204.00 ng/mL)" +
        'Before, 1 Mar 2024: 60.1 ng/mL, so down 56.2 ng/mL (93.5%)',
    ])
    expect(within(attention).getByText(/They are not a diagnosis/)).toBeVisible()

    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    expect(headings).toEqual([
      'What stands out',
      'Complete blood count',
      'Iron studies',
      'Other tests',
    ])
    const iron = screen.getByRole('table', { name: 'Iron studies: latest results' })
    expect(within(iron).getByRole('row', { name: /Ferritin/ })).toHaveTextContent(
      'FerritinLatest: 3.9 ng/mLRange: 4.63 – 204.00LowCollected: 3 Mar 20252 results',
    )
    expect(within(iron).getByRole('link', { name: 'Ferritin' })).toHaveAttribute(
      'href',
      `${memberPath}/tests/metric-ferritin`,
    )
    // A test that is not in the dictionary has no chart to open.
    const other = screen.getByRole('table', { name: 'Other tests: latest results' })
    expect(within(other).queryByRole('link')).not.toBeInTheDocument()
    expect(within(other).getByText('Not compared')).toBeVisible()
  })

  it('say so when every latest result is in range', async () => {
    const { amma, memberPath, saved } = setup()
    saved(amma.id, '2025-03-03T02:35:00Z', [ferritin('', '48.3', 'normal')])
    renderApp(memberPath)
    expect(
      await screen.findByText(
        "Every latest result is within the lab's range, with no big changes.",
      ),
    ).toBeVisible()
  })

  it('refresh after a report is saved', async () => {
    const { api, amma, memberPath } = setup()
    const report = api.addReport(amma.id)
    api.finishProcessing(report.id)
    const { user } = renderApp(memberPath)
    expect(await screen.findByText(/No results yet/)).toBeVisible()

    await user.click(await screen.findByRole('link', { name: /Report of 28 Sept 2026/ }))
    await user.click(await screen.findByRole('button', { name: "Save to Amma's history" }))
    await screen.findByText("Saved 4 values to Amma's history.")
    const breadcrumb = screen.getByRole('navigation', { name: 'Breadcrumb' })
    await user.click(within(breadcrumb).getByRole('link', { name: 'Amma' }))

    expect(await screen.findByRole('table', { name: 'Iron studies: latest results' })).toBeVisible()
    expect(screen.queryByText(/No results yet/)).not.toBeInTheDocument()
  })
})

describe('a test’s page', () => {
  it('shows the latest result, a chart with the range, and every result', async () => {
    const { amma, memberPath, saved } = setup()
    const first = saved(amma.id, '2024-03-01T04:00:00Z', [ferritin('', '60.1', 'normal')])
    const second = saved(amma.id, '2025-03-03T02:35:00Z', [ferritin('', '3.9', 'low')])
    renderApp(`${memberPath}/tests/metric-ferritin`)

    expect(await screen.findByRole('heading', { level: 1, name: 'Ferritin' })).toBeVisible()
    expect(screen.getByText("Iron studies. Amma's results over time.")).toBeVisible()
    expect(screen.getByText('Protein that stores iron in the body.')).toBeVisible()
    expect(screen.getByText('Latest result').nextElementSibling).toHaveTextContent('3.9 ng/mLLow')
    expect(screen.getByText('Previous result').nextElementSibling).toHaveTextContent(
      '60.1 ng/mL on 1 Mar 2024In range',
    )

    // The chart (loaded on demand) is an image with a spoken summary, plus a legend.
    expect(
      await screen.findByRole('img', {
        name: 'Ferritin: 2 results from 1 Mar 2024 to 3 Mar 2025. Latest 3.9 ng/mL, Low.',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText("The lab's reference range")).toBeVisible()

    const table = screen.getByRole('table', { name: 'All Ferritin results, newest first' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((row) => row.textContent)).toEqual([
      '3 Mar 2025Result: 3.9 ng/mLRange: 4.63 – 204.00LowOpen the report of 3 Mar 2025',
      '1 Mar 2024Result: 60.1 ng/mLRange: 4.63 – 204.00In rangeOpen the report of 1 Mar 2024',
    ])
    expect(within(rows[1] ?? table).getByRole('link')).toHaveAttribute(
      'href',
      `${memberPath}/reports/${first.id}`,
    )
    expect(within(rows[0] ?? table).getByRole('link')).toHaveAttribute(
      'href',
      `${memberPath}/reports/${second.id}`,
    )
    expect(screen.getByText(/They are not a diagnosis/)).toBeVisible()
  })

  it('says which results cannot be drawn', async () => {
    const { amma, memberPath, saved } = setup()
    saved(amma.id, '2024-03-01T04:00:00Z', [ferritin('', '60.1', 'normal')])
    saved(amma.id, '2025-03-03T02:35:00Z', [
      { ...ferritin('', '<5', 'unknown'), value_numeric: null, value_canonical: null },
    ])
    renderApp(`${memberPath}/tests/metric-ferritin`)
    expect(await screen.findByText(/1 result is not on the chart \(not a number/)).toBeVisible()
  })

  it('is "not found" for a test the app does not know', async () => {
    const { memberPath } = setup()
    renderApp(`${memberPath}/tests/metric-unknown`)
    expect(await screen.findByRole('heading', { name: "This test can't be found" })).toBeVisible()
  })

  it('is "not found" under another family’s address', async () => {
    const { api, amma } = setup()
    const other = api.addFamily('Iyer family')
    renderApp(`/families/${other.id}/members/${amma.id}/tests/metric-ferritin`)
    expect(await screen.findByRole('heading', { name: "This test can't be found" })).toBeVisible()
  })
})

describe('the family overview', () => {
  it('shows every member’s latest out-of-range results side by side', async () => {
    const { api, family, amma, saved } = setup()
    const appa = api.addMember(family.id, {
      display_name: 'Appa',
      sex: 'male',
      date_of_birth: null,
    })
    const ravi = api.addMember(family.id, {
      display_name: 'Ravi',
      sex: 'male',
      date_of_birth: null,
    })
    saved(amma.id, '2025-03-03T02:35:00Z', [ferritin('', '3.9', 'low')])
    saved(ravi.id, '2025-06-01T04:00:00Z', [ferritin('', '120', 'normal')])
    renderApp(`/families/${family.id}`)

    const overview = await screen.findByRole('region', { name: 'What stands out, by member' })
    const panel = (name: string) => within(overview).getByRole('region', { name })

    expect(await within(overview).findByRole('region', { name: 'Amma' })).toHaveTextContent(
      'AmmaLatest report 3 Mar 2025, 1 test' +
        "LowFerritinBelow the lab's range (first result of this test)" +
        "Latest, 3 Mar 2025: 3.9 ng/mL (lab's range 4.63 – 204.00 ng/mL)" +
        'Explain in plain words',
    )
    expect(within(panel('Amma')).getByRole('link', { name: 'Ferritin' })).toHaveAttribute(
      'href',
      `/families/${family.id}/members/${amma.id}/tests/metric-ferritin`,
    )
    expect(panel('Ravi')).toHaveTextContent(
      "Every latest result is within the lab's range, with no big changes.",
    )
    expect(panel('Appa')).toHaveTextContent('No saved results yet')
    expect(within(panel('Appa')).getByRole('link', { name: 'Appa' })).toHaveAttribute(
      'href',
      `/families/${family.id}/members/${appa.id}`,
    )
  })
})
