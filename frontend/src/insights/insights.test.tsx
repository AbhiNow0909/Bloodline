import { act, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import type { Reading } from '../lib/types'
import { DISCLAIMER, fakeApi } from '../test/fakeApi'
import { renderApp } from '../test/render'
import { signIn } from '../test/session'

beforeEach(() => {
  signIn()
})

const reading = (fields: Partial<Reading>): Reading => ({
  patient_id: '',
  report_id: '',
  collected_at: '',
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

/** A test from the fake dictionary with its range, in its standard unit. */
const test =
  (metricId: string, unit: string, low: string, high: string) =>
  (value: string, flag: Reading['flag']) =>
    reading({
      canonical_metric_id: metricId,
      raw_name: metricId.toUpperCase(),
      value_text: value,
      value_numeric: value,
      unit,
      value_canonical: value,
      unit_canonical: unit,
      reference_low: low,
      reference_high: high,
      flag,
    })
const ferritin = test('metric-ferritin', 'ng/mL', '4.63', '204.00')
const hb = test('metric-hb', 'g/dL', '12.0', '15.0')
const b12 = test('metric-b12', 'pg/mL', '197', '771')

function setup() {
  const api = fakeApi()
  const family = api.addFamily('Rao family')
  const amma = api.addMember(family.id, {
    display_name: 'Amma',
    sex: 'female',
    date_of_birth: null,
  })
  const memberPath = `/families/${family.id}/members/${amma.id}`
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
  // Ferritin fell below the range; haemoglobin came back into it; B12 rose 50 % in range; a
  // test that is not in the dictionary is high.
  saved(amma.id, '2024-03-01T04:00:00Z', [
    ferritin('60.1', 'normal'),
    hb('11.2', 'low'),
    b12('300', 'normal'),
  ])
  saved(amma.id, '2025-03-03T02:35:00Z', [
    ferritin('3.9', 'low'),
    hb('13.5', 'normal'),
    b12('450', 'normal'),
    reading({
      raw_name: 'URINE PROTEIN',
      value_text: '40',
      unit: 'mg/dL',
      reference_high: '15',
      flag: 'high',
    }),
  ])
  return { api, family, amma, memberPath, saved }
}

const panel = () => screen.findByRole('region', { name: 'What stands out' })
const explainRequests = (api: ReturnType<typeof fakeApi>) =>
  api.calls.filter((c) => c.path.endsWith('/insights/explain'))

describe('what stands out on a member’s page', () => {
  it('lists each finding with its status in words, most important first', async () => {
    const { family, amma } = setup()
    renderApp(`/families/${family.id}/members/${amma.id}`)

    const rows = within(await panel()).getAllByRole('listitem')
    expect(rows.map((row) => row.textContent)).toEqual([
      "LowFerritinMoved below the lab's range" +
        "Latest, 3 Mar 2025: 3.9 ng/mL (lab's range 4.63 – 204.00 ng/mL)" +
        'Before, 1 Mar 2024: 60.1 ng/mL, so down 56.2 ng/mL (93.5%)',
      "RisingVitamin B12Rose by 50% across the last 2 results, still within the lab's range" +
        "Latest, 3 Mar 2025: 450 pg/mL (lab's range 197 – 771 pg/mL)" +
        'Before, 1 Mar 2024: 300 pg/mL, so up 150 pg/mL (50%)',
      "In rangeHemoglobinBack within the lab's range, after being below it" +
        "Latest, 3 Mar 2025: 13.5 g/dL (lab's range 12.0 – 15.0 g/dL)" +
        'Before, 1 Mar 2024: 11.2 g/dL, so up 2.3 g/dL (20.5%)',
      "HighURINE PROTEINOutside the lab's range" +
        "Latest, 3 Mar 2025: 40 mg/dL (lab's range up to 15 mg/dL)",
    ])
    expect(within(rows[0] as HTMLElement).getByRole('link', { name: 'Ferritin' })).toHaveAttribute(
      'href',
      `/families/${family.id}/members/${amma.id}/tests/metric-ferritin`,
    )
    // A test outside the dictionary has no chart to open.
    expect(within(rows[3] as HTMLElement).queryByRole('link')).not.toBeInTheDocument()
  })

  it('explains the findings in plain words when asked, with the disclaimer', async () => {
    const { api, memberPath } = setup()
    api.explainWith('Ferritin reflects iron stores; this result is lower than usual.')
    const release = api.holdAi()
    const { user } = renderApp(memberPath)
    const region = await panel()
    expect(within(region).queryByText(/In plain words/)).not.toBeInTheDocument()
    expect(explainRequests(api)).toEqual([]) // nothing is sent until asked

    await user.click(within(region).getByRole('button', { name: 'Explain in plain words' }))
    expect(within(region).getByRole('button', { name: 'Explaining…' })).toBeDisabled()
    expect(within(region).getByText('Writing explanations…')).toBeVisible()

    release()
    const [ferritinRow] = within(region).getAllByRole('listitem')
    expect(
      await within(ferritinRow as HTMLElement).findByText(
        'Ferritin reflects iron stores; this result is lower than usual.',
      ),
    ).toBeVisible()
    // The button is gone, so focus moves to the first explanation.
    expect(
      within(ferritinRow as HTMLElement).getByText(/Ferritin reflects iron stores/),
    ).toHaveFocus()
    expect(within(region).getByText('Vitamin B12, explained simply.')).toBeVisible()
    expect(within(region).getAllByText('In plain words:')).toHaveLength(3)
    expect(within(region).getByText(new RegExp(DISCLAIMER.slice(0, 40)))).toHaveTextContent(
      `The explanations are written by an AI from the results above. ${DISCLAIMER}`,
    )
    expect(within(region).queryByRole('button', { name: /Explain/ })).not.toBeInTheDocument()
    expect(explainRequests(api)).toHaveLength(1)
  })

  it('shows why explaining failed, and tries again', async () => {
    const { api, memberPath } = setup()
    let busy = true
    api.override((call) =>
      busy && call.path.endsWith('/explain')
        ? {
            status: 503,
            body: { detail: 'The assistant is busy right now. Please try again in a minute.' },
          }
        : undefined,
    )
    const { user } = renderApp(memberPath)
    const region = await panel()

    await user.click(within(region).getByRole('button', { name: 'Explain in plain words' }))
    expect(await within(region).findByRole('alert')).toHaveTextContent(
      'The assistant is busy right now. Please try again in a minute.',
    )

    busy = false
    await user.click(within(region).getByRole('button', { name: 'Try again' }))
    expect(await within(region).findByText('Ferritin, explained simply.')).toBeVisible()
    expect(within(region).queryByRole('alert')).not.toBeInTheDocument()
  })

  it('keeps explanations for the family page, and drops them when the findings change', async () => {
    const { api, family, amma, memberPath, saved } = setup()
    const { user, router, queryClient } = renderApp(memberPath)
    await user.click(within(await panel()).getByRole('button', { name: 'Explain in plain words' }))
    await screen.findByText('Ferritin, explained simply.')

    // The family page shows the same explanations without asking again.
    await act(() => router.navigate(`/families/${family.id}`))
    const ammaCard = await screen.findByRole('region', { name: 'Amma' })
    expect(within(ammaCard).getByText('Ferritin, explained simply.')).toBeVisible()
    expect(explainRequests(api)).toHaveLength(1)

    // A newer report changes the findings: the old explanations no longer apply.
    saved(amma.id, '2025-09-05T02:45:00Z', [ferritin('20.0', 'normal')])
    await act(() => queryClient.invalidateQueries())
    await act(() => router.navigate(memberPath))
    const region = await panel()
    // Ferritin is now back within the range too (like haemoglobin).
    expect(
      await within(region).findAllByText(/Back within the lab's range, after being below/),
    ).toHaveLength(2)
    expect(within(region).queryByText(/explained simply/)).not.toBeInTheDocument()
    expect(within(region).getByRole('button', { name: 'Explain in plain words' })).toBeEnabled()
  })

  it('says so when nothing stands out', async () => {
    const api = fakeApi()
    const family = api.addFamily('Rao family')
    const amma = api.addMember(family.id, {
      display_name: 'Amma',
      sex: 'female',
      date_of_birth: null,
    })
    const report = api.addReport(amma.id, {
      status: 'confirmed',
      collected_at: '2025-03-03T02:35:00Z',
    })
    const entry = api.reports.get(report.id)
    if (entry) {
      entry.readings = [
        {
          ...ferritin('48.3', 'normal'),
          patient_id: amma.id,
          report_id: report.id,
          collected_at: '2025-03-03T02:35:00Z',
        },
      ]
    }
    renderApp(`/families/${family.id}/members/${amma.id}`)

    expect(
      await screen.findByText(
        "Every latest result is within the lab's range, with no big changes.",
      ),
    ).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Explain in plain words' })).not.toBeInTheDocument()
  })
})

describe('what stands out on the family page', () => {
  it('lists each member’s findings and explains one member at a time', async () => {
    const { api, family, saved } = setup()
    const appa = api.addMember(family.id, {
      display_name: 'Appa',
      sex: 'male',
      date_of_birth: null,
    })
    saved(appa.id, '2025-06-01T04:00:00Z', [hb('16.1', 'high')])
    const { user } = renderApp(`/families/${family.id}`)

    const overview = await screen.findByRole('region', { name: 'What stands out, by member' })
    const appaCard = within(overview).getByRole('region', { name: 'Appa' })
    expect(within(appaCard).getByRole('listitem')).toHaveTextContent(
      "HighHemoglobinAbove the lab's range (first result of this test)",
    )
    const ammaCard = within(overview).getByRole('region', { name: 'Amma' })
    expect(within(ammaCard).getAllByRole('listitem')).toHaveLength(4)

    await user.click(within(appaCard).getByRole('button', { name: 'Explain in plain words' }))
    expect(await within(appaCard).findByText('Hemoglobin, explained simply.')).toBeVisible()
    expect(within(ammaCard).queryByText(/In plain words/)).not.toBeInTheDocument()
    expect(explainRequests(api).map((c) => c.path)).toEqual([
      `/patients/${appa.id}/insights/explain`,
    ])
  })
})
