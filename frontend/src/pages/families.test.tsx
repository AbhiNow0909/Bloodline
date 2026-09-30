import { screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { fakeApi } from '../test/fakeApi'
import { renderApp } from '../test/render'
import { signIn } from '../test/session'

beforeEach(() => {
  signIn()
})

describe('families list', () => {
  it('shows each family as a folder with its member count', async () => {
    const api = fakeApi()
    const rao = api.addFamily('Rao family')
    api.addMember(rao.id, { display_name: 'Amma', sex: 'female', date_of_birth: null })
    api.addMember(rao.id, { display_name: 'Appa', sex: 'male', date_of_birth: null })
    api.addFamily('Iyer family')
    renderApp('/families')

    const link = await screen.findByRole('link', { name: /Rao family/ })
    const rows = within(link.closest('ul') ?? document.body).getAllByRole('listitem')
    expect(rows.map((row) => row.textContent)).toEqual([
      'Iyer family0 members',
      'Rao family2 members',
      'New familyA folder for a group of people',
    ])
    expect(link).toHaveAttribute('href', `/families/${rao.id}`)
    expect(document.title).toBe('Families – Bloodline')
  })

  it('invites the user to create a first family', async () => {
    fakeApi()
    renderApp('/families')
    expect(await screen.findByText(/You have no families yet/)).toBeInTheDocument()
  })

  it('creates a family and opens it', async () => {
    const api = fakeApi()
    const { user, router } = renderApp('/families')

    await user.click(await screen.findByRole('button', { name: /New family/ }))
    const dialog = screen.getByRole('dialog', { name: 'New family' })
    await user.type(within(dialog).getByLabelText('Family name'), '  Rao family  ')
    await user.click(within(dialog).getByRole('button', { name: 'Create family' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Rao family' })).toBeInTheDocument()
    const [created] = api.families.values()
    expect(created?.name).toBe('Rao family')
    expect(router.state.location.pathname).toBe(`/families/${created?.id ?? ''}`)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('explains a duplicate name and keeps the dialog open', async () => {
    const api = fakeApi()
    api.addFamily('Rao family')
    const { user } = renderApp('/families')

    await user.click(await screen.findByRole('button', { name: /New family/ }))
    const dialog = screen.getByRole('dialog', { name: 'New family' })
    await user.type(within(dialog).getByLabelText('Family name'), 'Rao family')
    await user.click(within(dialog).getByRole('button', { name: 'Create family' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'You already have a family with this name',
    )
    expect(api.families.size).toBe(1)
  })

  it('requires a name', async () => {
    const api = fakeApi()
    const { user } = renderApp('/families')
    await user.click(await screen.findByRole('button', { name: /New family/ }))
    const dialog = screen.getByRole('dialog', { name: 'New family' })
    await user.type(within(dialog).getByLabelText('Family name'), '   ')
    await user.click(within(dialog).getByRole('button', { name: 'Create family' }))

    expect(within(dialog).getByLabelText('Family name')).toHaveAccessibleDescription(
      "For example, Sharma family or Mum's side. Enter a name for the family.",
    )
    expect(within(dialog).getByLabelText('Family name')).toHaveFocus()
    expect(api.writes()).toHaveLength(0)
  })

  it('starts the create dialog fresh each time it opens', async () => {
    fakeApi()
    const { user } = renderApp('/families')
    await user.click(await screen.findByRole('button', { name: /New family/ }))
    await user.type(screen.getByLabelText('Family name'), 'Half typed')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /New family/ }))
    expect(screen.getByLabelText('Family name')).toHaveValue('')
  })
})

describe('a family', () => {
  it('can be renamed', async () => {
    const api = fakeApi()
    const family = api.addFamily('Rao family')
    const { user } = renderApp(`/families/${family.id}`)

    await user.click(await screen.findByRole('button', { name: 'Rename' }))
    const field = screen.getByLabelText('Family name')
    expect(field).toHaveValue('Rao family')
    await user.clear(field)
    await user.type(field, 'Rao–Iyer family')
    await user.click(screen.getByRole('button', { name: 'Save name' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Rao–Iyer family' })).toBeVisible()
    expect(api.families.get(family.id)?.name).toBe('Rao–Iyer family')
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent(
      'FamiliesRao–Iyer family',
    )
  })

  it('is deleted only after confirming, with the consequence spelled out', async () => {
    const api = fakeApi()
    const family = api.addFamily('Rao family')
    api.addMember(family.id, { display_name: 'Amma', sex: 'female', date_of_birth: null })
    const { user, router } = renderApp(`/families/${family.id}`)

    await user.click(await screen.findByRole('button', { name: 'Delete family' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete Rao family?' })
    expect(dialog).toHaveTextContent(
      'This permanently deletes the family, its 1 member and all of their reports and results.',
    )
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(api.writes()).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Delete family' }))
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete family' }),
    )

    expect(await screen.findByText(/You have no families yet/)).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/families')
    expect(api.families.size).toBe(0)
    expect(api.writes()).toEqual([expect.objectContaining({ method: 'DELETE' })])
  })

  it('shows "not found" for a family that does not exist or is not yours', async () => {
    fakeApi()
    renderApp('/families/someone-elses-family')
    expect(await screen.findByRole('heading', { name: "This family can't be found" })).toBeVisible()
    expect(screen.getByRole('link', { name: 'Go to your families' })).toHaveAttribute(
      'href',
      '/families',
    )
  })

  it('shows "not found" for an unknown address', async () => {
    fakeApi()
    renderApp('/no/such/page')
    expect(await screen.findByRole('heading', { name: "This page can't be found" })).toBeVisible()
  })

  it('shows a server error instead of an empty page', async () => {
    const api = fakeApi()
    const family = api.addFamily('Rao family')
    api.override((call) =>
      call.path.endsWith('/patients') ? { status: 503, body: { detail: 'down' } } : undefined,
    )
    renderApp(`/families/${family.id}`)
    expect(await screen.findByRole('alert')).toHaveTextContent('down')
    // Server errors are retried twice before the error is shown.
    expect(api.calls.filter((c) => c.path.endsWith('/patients'))).toHaveLength(3)
  })
})
