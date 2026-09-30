import { session } from './session'
import type { Family, Member, MemberInput, TokenResponse, User } from './types'

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(
  /\/+$/,
  '',
)

/** A failed API call, with a message written for the person using the app. */
export class ApiError extends Error {
  readonly status: number
  /** Messages for individual fields, from 422 validation errors (keyed by field name). */
  readonly fieldErrors: Readonly<Record<string, string>>

  constructor(status: number, message: string, fieldErrors: Record<string, string> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.fieldErrors = fieldErrors
  }
}

/** What to tell the user about any error thrown while talking to the API. */
export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Something went wrong. Try again.'
}

export const NETWORK_ERROR =
  "Can't reach the Bloodline server. Check your internet connection and try again."

interface ValidationIssue {
  loc?: unknown[]
  msg?: string
}

async function toApiError(response: Response): Promise<ApiError> {
  let detail: unknown = null
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail
  } catch {
    // not JSON (e.g. a proxy error page)
  }
  if (typeof detail === 'string') return new ApiError(response.status, detail)
  if (Array.isArray(detail)) {
    const fieldErrors: Record<string, string> = {}
    for (const issue of detail as ValidationIssue[]) {
      const field = issue.loc?.at(-1)
      if (typeof field === 'string' && issue.msg && !(field in fieldErrors)) {
        fieldErrors[field] = issue.msg.replace(/^Value error, /, '')
      }
    }
    return new ApiError(response.status, 'Some details need fixing.', fieldErrors)
  }
  if (typeof detail === 'object' && detail !== null && 'message' in detail) {
    return new ApiError(response.status, String(detail.message))
  }
  return new ApiError(
    response.status,
    response.status >= 500
      ? 'Something went wrong on the server. Try again in a minute.'
      : `The request failed (${response.status}).`,
  )
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  json?: unknown
  signal?: AbortSignal
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const current = session.get()
  // The expiry timer can fire late (e.g. after the computer sleeps): end the session now.
  if (current !== null && current.expiresAt <= Date.now()) session.clear()
  const token = session.get()?.token
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.json !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body: options.json === undefined ? undefined : JSON.stringify(options.json),
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0, NETWORK_ERROR)
  }

  // An expired or revoked token: sign out everywhere; the router sends the user to login.
  if (response.status === 401 && token) session.clear()
  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

// --- endpoints ------------------------------------------------------------------------------

export const api = {
  login: (email: string, password: string) =>
    request<TokenResponse>('/auth/login', { method: 'POST', json: { email, password } }),
  me: () => request<User>('/auth/me'),

  families: () => request<Family[]>('/families'),
  family: (id: string) => request<Family>(`/families/${id}`),
  createFamily: (name: string) => request<Family>('/families', { method: 'POST', json: { name } }),
  renameFamily: (id: string, name: string) =>
    request<Family>(`/families/${id}`, { method: 'PATCH', json: { name } }),
  deleteFamily: (id: string) => request<undefined>(`/families/${id}`, { method: 'DELETE' }),

  members: (familyId: string) => request<Member[]>(`/families/${familyId}/patients`),
  member: (id: string) => request<Member>(`/patients/${id}`),
  addMember: (familyId: string, input: MemberInput) =>
    request<Member>(`/families/${familyId}/patients`, { method: 'POST', json: input }),
  updateMember: (id: string, input: Partial<MemberInput>) =>
    request<Member>(`/patients/${id}`, { method: 'PATCH', json: input }),
  deleteMember: (id: string) => request<undefined>(`/patients/${id}`, { method: 'DELETE' }),
}
