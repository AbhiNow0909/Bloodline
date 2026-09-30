import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { session } from '../lib/session'
import { PASSWORD, USER, fakeApi } from '../test/fakeApi'
import { renderApp } from '../test/render'
import { signIn } from '../test/session'

async function signInWith(user: ReturnType<typeof renderApp>['user'], email: string, pw: string) {
  await user.type(screen.getByLabelText('Email address'), email)
  await user.type(screen.getByLabelText('Password'), pw)
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('signing in', () => {
  it('sends a signed-out visitor to sign in, then back to the page they asked for', async () => {
    const api = fakeApi()
    const family = api.addFamily('Rao family')
    const { user, router } = renderApp(`/families/${family.id}`)

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
    expect(api.calls).toHaveLength(0) // nothing is requested before signing in

    await signInWith(user, `  ${USER.email} `, PASSWORD)

    expect(await screen.findByRole('heading', { name: 'Rao family' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe(`/families/${family.id}`)
    expect(session.get()).not.toBeNull()
    expect(api.calls[0]).toMatchObject({
      method: 'POST',
      path: '/auth/login',
      body: { email: USER.email, password: PASSWORD },
      authorization: null,
    })
    expect(await screen.findByText(USER.display_name)).toBeInTheDocument()
  })

  it('goes to the families list by default', async () => {
    fakeApi()
    const { user, router } = renderApp('/login')
    await signInWith(user, USER.email, PASSWORD)
    expect(await screen.findByRole('heading', { name: 'Families' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/families')
  })

  it('shows the server message for a wrong password and stays signed out', async () => {
    fakeApi()
    const { user, router } = renderApp('/login')
    await signInWith(user, USER.email, 'wrong password')

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password')
    expect(router.state.location.pathname).toBe('/login')
    expect(session.get()).toBeNull()
  })

  it('asks for missing details without calling the server', async () => {
    const api = fakeApi()
    const { user } = renderApp('/login')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(screen.getByLabelText('Email address')).toHaveAccessibleDescription(
      'Enter your email address.',
    )
    expect(screen.getByLabelText('Password')).toHaveAccessibleDescription('Enter your password.')
    expect(screen.getByLabelText('Email address')).toHaveFocus()
    expect(api.calls).toHaveLength(0)
  })

  it('can show the password while typing it', async () => {
    const { user } = renderApp('/login')
    const password = screen.getByLabelText('Password')
    expect(password).toHaveAttribute('type', 'password')
    await user.click(screen.getByLabelText('Show password'))
    expect(password).toHaveAttribute('type', 'text')
  })

  it('skips the sign-in page when already signed in', async () => {
    fakeApi()
    signIn()
    const { router } = renderApp('/login')
    expect(await screen.findByRole('heading', { name: 'Families' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/families')
  })
})

describe('signing out', () => {
  it('forgets every cached family and member', async () => {
    const api = fakeApi()
    api.addFamily('Rao family')
    signIn()
    const { user, queryClient } = renderApp('/families')
    expect(await screen.findByRole('link', { name: /Rao family/ })).toBeInTheDocument()
    expect(queryClient.getQueryCache().getAll().length).toBeGreaterThan(0)

    await user.click(screen.getByRole('button', { name: 'Log out' }))

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(session.get()).toBeNull()
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
    expect(screen.queryByText('Rao family')).not.toBeInTheDocument()
  })

  it('happens when the server no longer accepts the session', async () => {
    const api = fakeApi()
    api.override((call) =>
      call.path === '/families' ? { status: 401, body: { detail: 'Invalid token' } } : undefined,
    )
    signIn()
    const { router } = renderApp('/families')

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/login')
    })
    expect(session.get()).toBeNull()
  })
})
