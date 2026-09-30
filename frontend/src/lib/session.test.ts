import { afterEach, describe, expect, it, vi } from 'vitest'

import { fakeToken } from '../test/session'
import { session, tokenExpiry } from './session'

const STORAGE_KEY = 'bloodline.session'

describe('tokenExpiry', () => {
  it('reads the exp claim in milliseconds', () => {
    vi.useFakeTimers({ now: new Date('2026-09-30T00:00:00Z') })
    expect(tokenExpiry(fakeToken(60))).toBe(Date.parse('2026-09-30T00:01:00Z'))
  })

  it.each(['', 'not-a-jwt', 'a.!!!.c', `a.${btoa('{"sub":"x"}')}.c`, `a.${btoa('"exp"')}.c`])(
    'returns null for an unreadable token (%s)',
    (token) => {
      expect(tokenExpiry(token)).toBeNull()
    },
  )
})

describe('session', () => {
  afterEach(() => {
    session.clear()
  })

  it('starts, is stored for reloads and new tabs, and clears', () => {
    const token = fakeToken()
    expect(session.start(token)).toBe(true)
    expect(session.get()?.token).toBe(token)
    expect(localStorage.getItem(STORAGE_KEY)).toContain(token)

    session.clear()
    expect(session.get()).toBeNull()
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('refuses an expired or unreadable token', () => {
    expect(session.start(fakeToken(-1))).toBe(false)
    expect(session.start('garbage')).toBe(false)
    expect(session.get()).toBeNull()
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('signs out when the token expires', () => {
    vi.useFakeTimers()
    const listener = vi.fn()
    const unsubscribe = session.subscribe(listener)
    session.start(fakeToken(60))
    listener.mockClear()

    vi.advanceTimersByTime(59_000)
    expect(session.get()).not.toBeNull()
    vi.advanceTimersByTime(1_000)
    expect(session.get()).toBeNull()
    expect(listener).toHaveBeenCalled()
    unsubscribe()
  })

  it('restores a stored session but ignores an expired or malformed one', () => {
    const token = fakeToken()
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, expiresAt: Date.now() + 60_000 }))
    session.restore()
    expect(session.get()?.token).toBe(token)

    localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, expiresAt: Date.now() - 1 }))
    session.restore()
    expect(session.get()).toBeNull()

    localStorage.setItem(STORAGE_KEY, '{not json')
    session.restore()
    expect(session.get()).toBeNull()
  })

  it('follows sign-in and sign-out in another tab', () => {
    const token = fakeToken()
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, expiresAt: Date.now() + 60_000 }))
    window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY }))
    expect(session.get()?.token).toBe(token)

    localStorage.removeItem(STORAGE_KEY)
    window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY }))
    expect(session.get()).toBeNull()
  })

  it('keeps the same object between reads (safe for useSyncExternalStore)', () => {
    session.start(fakeToken())
    expect(session.get()).toBe(session.get())
  })
})
