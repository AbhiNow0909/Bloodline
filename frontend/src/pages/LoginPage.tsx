import { useMutation } from '@tanstack/react-query'
import { useEffect, useState, type SubmitEvent } from 'react'
import { Navigate, useLocation } from 'react-router'

import { Button } from '../components/Button'
import { ErrorState } from '../components/States'
import { TextField } from '../components/TextField'
import { TubeRack, Wordmark } from '../components/Wordmark'
import { ApiError, api } from '../lib/api'
import { focusFirstField } from '../lib/forms'
import { useSession } from '../lib/queries'
import { session } from '../lib/session'

const CLOCK_ERROR = new ApiError(
  0,
  "Couldn't start your session. Check that this device's date and time are correct.",
)

/** Only same-app paths are followed after signing in. */
function returnPath(state: unknown): string {
  if (typeof state === 'object' && state !== null && 'from' in state) {
    const { from } = state
    if (typeof from === 'string' && from.startsWith('/') && !from.startsWith('//')) return from
  }
  return '/families'
}

export function LoginPage() {
  const current = useSession()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [missing, setMissing] = useState<{ email?: string; password?: string }>({})

  const login = useMutation({
    mutationFn: async () => {
      const token = await api.login(email.trim(), password)
      if (!session.start(token.access_token)) throw CLOCK_ERROR
    },
  })

  useEffect(() => {
    document.title = 'Sign in – Bloodline'
  }, [])

  // Signed in (now, or already in another tab): continue to where the user was going.
  if (current !== null) return <Navigate to={returnPath(location.state)} replace />

  function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    const found = {
      email: email.trim() ? undefined : 'Enter your email address.',
      password: password ? undefined : 'Enter your password.',
    }
    setMissing(found)
    if (found.email || found.password) {
      focusFirstField(event.currentTarget, found.email ? ['email'] : ['password'])
      return
    }
    login.mutate()
  }

  return (
    <div className="flex min-h-dvh items-center justify-center px-4 py-10">
      <main className="w-full max-w-md">
        <div className="flex items-end justify-between gap-4">
          <Wordmark className="text-xl" />
          <TubeRack className="w-24 sm:w-28" />
        </div>
        <div className="mt-4 rounded-xl border border-line bg-surface p-6 sm:p-8">
          <h1 className="text-xl font-bold tracking-tight">Sign in</h1>
          <p className="mt-2 text-muted">
            Your family's lab reports and results, kept in one place.
          </p>

          <form noValidate onSubmit={handleSubmit} className="mt-6 flex flex-col gap-5">
            <TextField
              label="Email address"
              name="email"
              type="email"
              autoComplete="username"
              inputMode="email"
              spellCheck={false}
              value={email}
              onChange={(event) => {
                setEmail(event.target.value)
              }}
              error={missing.email}
            />
            <div className="flex flex-col gap-2">
              <TextField
                label="Password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value)
                }}
                error={missing.password}
              />
              <label className="flex min-h-11 w-fit cursor-pointer items-center gap-3">
                <input
                  type="checkbox"
                  checked={showPassword}
                  onChange={(event) => {
                    setShowPassword(event.target.checked)
                  }}
                  className="size-5 accent-edta"
                />
                Show password
              </label>
            </div>
            {login.error && <ErrorState error={login.error} />}
            <Button type="submit" disabled={login.isPending} className="w-full">
              {login.isPending ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>
        </div>
        <p className="mt-4 text-sm text-muted">
          There is no sign-up. Ask whoever set up Bloodline for your family to create an account for
          you.
        </p>
      </main>
    </div>
  )
}
