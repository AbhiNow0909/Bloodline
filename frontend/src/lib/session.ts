/**
 * The signed-in session: the API's bearer token and when it expires.
 *
 * Kept in localStorage so a reload or a new tab stays signed in until the token expires
 * (24 h by default). The app never renders HTML from data, which is the main defence for a
 * token stored this way. Signing out in one tab signs out every tab, and a timer signs out
 * when the token expires.
 */

const STORAGE_KEY = 'bloodline.session'
const MAX_TIMEOUT_MS = 2_147_483_647 // setTimeout's limit (~24.8 days)

export interface Session {
  token: string
  expiresAt: number // milliseconds since the epoch
}

type Listener = () => void

/** The `exp` claim of a JWT, in milliseconds; null if the token is unreadable. The signature
 * is checked by the server, never here. */
export function tokenExpiry(token: string): number | null {
  const payload = token.split('.')[1]
  if (!payload) return null
  try {
    const claims: unknown = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')))
    if (typeof claims === 'object' && claims !== null && 'exp' in claims) {
      return typeof claims.exp === 'number' ? claims.exp * 1000 : null
    }
    return null
  } catch {
    return null
  }
}

function readStored(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Session>
    if (typeof parsed.token !== 'string' || typeof parsed.expiresAt !== 'number') return null
    return parsed.expiresAt > Date.now()
      ? { token: parsed.token, expiresAt: parsed.expiresAt }
      : null
  } catch {
    return null
  }
}

let current: Session | null = null
let expiryTimer: ReturnType<typeof setTimeout> | undefined
const listeners = new Set<Listener>()

function update(next: Session | null): void {
  current = next
  clearTimeout(expiryTimer)
  if (next !== null) {
    const delay = Math.min(Math.max(next.expiresAt - Date.now(), 0), MAX_TIMEOUT_MS)
    expiryTimer = setTimeout(() => {
      session.clear()
    }, delay)
  }
  for (const listener of listeners) listener()
}

export const session = {
  /** The current session (stable object identity, so it can back useSyncExternalStore). */
  get: (): Session | null => current,

  /** Store a token from POST /auth/login. Returns false if it is unreadable or expired. */
  start: (token: string): boolean => {
    const expiresAt = tokenExpiry(token)
    if (expiresAt === null || expiresAt <= Date.now()) return false
    const next = { token, expiresAt }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    update(next)
    return true
  },

  clear: (): void => {
    localStorage.removeItem(STORAGE_KEY)
    if (current !== null) update(null)
  },

  subscribe: (listener: Listener): (() => void) => {
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  },

  /** Load the stored session (at startup, and in tests). */
  restore: (): void => {
    update(readStored())
  },
}

session.restore()

// Another tab signed in or out.
window.addEventListener('storage', (event) => {
  if (event.key === STORAGE_KEY || event.key === null) session.restore()
})
