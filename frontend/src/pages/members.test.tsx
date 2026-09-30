import { screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fakeApi } from '../test/fakeApi'
import { renderApp } from '../test/render'
import { signIn } from '../test/session'

beforeEach(() => {
  // Only Date is faked, so "today" is fixed while timers and promises run normally. Sign in
  // after faking it, so the session's expiry is measured on the same clock.
  vi.useFakeTimers({ now: new Date(2026, 8, 30, 12), toFake: ['Date'] })
  signIn()
})

/** The family page's member cards (the overview below also names each member). */
const membersSection = () => screen.findByRole('region', { name: 'Family members' })

function setup() {
  const api = fakeApi()
  const family = api.addFamily('Rao family')
  const amma = api.addMember(family.id, {
    display_name: 'Amma',
    sex: 'female',
    date_of_birth: '1968-03-01',
  })
  return { api, family, amma }
}

describe('members of a family', () => {
  it('are listed like files, with sex and age', async () => {
    const { family, amma } = setup()
    renderApp(`/families/${family.id}`)

    const link = await within(await membersSection()).findByRole('link', { name: /Amma/ })
    expect(link).toHaveTextContent('AmmaFemale, 58 years')
    expect(link).toHaveAttribute('href', `/families/${family.id}/members/${amma.id}`)
    expect(screen.getByText('1 member')).toBeInTheDocument()
  })

  it('can be added, with the date of birth optional', async () => {
    const { api, family } = setup()
    const { user } = renderApp(`/families/${family.id}`)

    await user.click(await screen.findByRole('button', { name: /Add family member/ }))
    const dialog = screen.getByRole('dialog', { name: 'Add someone to Rao family' })
    await user.type(within(dialog).getByLabelText('Name'), ' Ravi ')
    await user.click(within(dialog).getByLabelText('Male'))
    await user.click(within(dialog).getByRole('button', { name: 'Add member' }))

    expect(
      await within(await membersSection()).findByRole('link', { name: /Ravi/ }),
    ).toHaveTextContent('RaviMale')
    expect(screen.getByText('2 members')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.writes()).toEqual([
      expect.objectContaining({
        method: 'POST',
        path: `/families/${family.id}/patients`,
        body: { display_name: 'Ravi', sex: 'male', date_of_birth: null },
      }),
    ])
  })

  it('need a name and a sex, and a date of birth in the past', async () => {
    const { api, family } = setup()
    const { user } = renderApp(`/families/${family.id}`)

    await user.click(await screen.findByRole('button', { name: /Add family member/ }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByLabelText('Date of birth (optional)'), '2026-09-30')
    await user.click(within(dialog).getByRole('button', { name: 'Add member' }))

    expect(within(dialog).getByText('Enter a name.')).toBeVisible()
    expect(within(dialog).getByRole('group', { name: 'Sex' })).toHaveAccessibleDescription(
      'Lab reports print different reference ranges for women and men. Choose female or male.',
    )
    expect(within(dialog).getByText('Enter a date of birth before today.')).toBeVisible()
    expect(within(dialog).getByLabelText('Name')).toHaveFocus() // the first field to fix
    expect(api.writes()).toHaveLength(0)
  })

  it('show field errors returned by the server', async () => {
    const { api, family } = setup()
    api.override((call) =>
      call.method === 'POST'
        ? {
            status: 422,
            body: {
              detail: [{ loc: ['body', 'date_of_birth'], msg: 'Date should be in the past' }],
            },
          }
        : undefined,
    )
    const { user } = renderApp(`/families/${family.id}`)

    await user.click(await screen.findByRole('button', { name: /Add family member/ }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByLabelText('Name'), 'Ravi')
    await user.click(within(dialog).getByLabelText('Male'))
    await user.type(within(dialog).getByLabelText('Date of birth (optional)'), '1990-01-01')
    await user.click(within(dialog).getByRole('button', { name: 'Add member' }))

    expect(await within(dialog).findByText('Date should be in the past')).toBeVisible()
    expect(within(dialog).getByLabelText('Date of birth (optional)')).toBeInvalid()
  })
})

describe('a member page', () => {
  it('shows the path, details and the reports section', async () => {
    const { family, amma } = setup()
    renderApp(`/families/${family.id}/members/${amma.id}`)

    expect(await screen.findByRole('heading', { level: 1, name: 'Amma' })).toBeVisible()
    const breadcrumb = screen.getByRole('navigation', { name: 'Breadcrumb' })
    expect(within(breadcrumb).getByRole('link', { name: 'Rao family' })).toHaveAttribute(
      'href',
      `/families/${family.id}`,
    )
    expect(within(breadcrumb).getByText('Amma')).toHaveAttribute('aria-current', 'page')
    expect(screen.getByText('1 Mar 1968')).toBeVisible()
    expect(screen.getByText('58 years')).toBeVisible()
    expect(await screen.findByText('No reports yet.')).toBeVisible()
    expect(screen.getByLabelText('Choose a PDF')).toBeInTheDocument()
  })

  it('edits details, and clearing the date of birth sends null', async () => {
    const { api, family, amma } = setup()
    const { user } = renderApp(`/families/${family.id}/members/${amma.id}`)

    await user.click(await screen.findByRole('button', { name: 'Edit details' }))
    const dialog = screen.getByRole('dialog', { name: "Edit Amma's details" })
    const name = within(dialog).getByLabelText('Name')
    expect(name).toHaveValue('Amma')
    expect(within(dialog).getByLabelText('Female')).toBeChecked()
    await user.clear(name)
    await user.type(name, 'Mum')
    await user.clear(within(dialog).getByLabelText('Date of birth (optional)'))
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Mum' })).toBeVisible()
    expect(screen.getByText('Not given')).toBeVisible()
    expect(api.writes()).toEqual([
      expect.objectContaining({
        method: 'PATCH',
        path: `/patients/${amma.id}`,
        body: { display_name: 'Mum', sex: 'female', date_of_birth: null },
      }),
    ])
  })

  it('deletes the member after confirming and returns to the family', async () => {
    const { api, family, amma } = setup()
    const { user, router } = renderApp(`/families/${family.id}/members/${amma.id}`)

    await user.click(await screen.findByRole('button', { name: 'Delete member' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete Amma?' })
    expect(dialog).toHaveTextContent(
      'This permanently deletes Amma from Rao family, with all of their reports and results.',
    )
    await user.click(within(dialog).getByRole('button', { name: 'Delete member' }))

    expect(await screen.findByText('0 members')).toBeVisible()
    expect(router.state.location.pathname).toBe(`/families/${family.id}`)
    expect(
      within(await membersSection()).queryByRole('link', { name: /Amma/ }),
    ).not.toBeInTheDocument()
    expect(api.members.size).toBe(0)

    // Back skips the deleted page (it was replaced); opening its address again shows
    // "not found", not a cached copy.
    await router.navigate(-1)
    expect(router.state.location.pathname).toBe(`/families/${family.id}`)
    await router.navigate(`/families/${family.id}/members/${amma.id}`)
    expect(
      await screen.findByRole('heading', { name: "This family member can't be found" }),
    ).toBeVisible()
  })

  it('is "not found" under another family\'s address', async () => {
    const { api, amma } = setup()
    const other = api.addFamily('Iyer family')
    renderApp(`/families/${other.id}/members/${amma.id}`)
    expect(
      await screen.findByRole('heading', { name: "This family member can't be found" }),
    ).toBeVisible()
  })
})
