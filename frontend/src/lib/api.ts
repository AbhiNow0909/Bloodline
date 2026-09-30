import { session } from './session'
import type {
  CatalogEntry,
  ConfirmReportInput,
  Family,
  FamilyOverview,
  Member,
  MemberInput,
  MetricDefinition,
  MetricHistory,
  Reading,
  Report,
  ReportReview,
  ReportSummary,
  TokenResponse,
  User,
} from './types'

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(
  /\/+$/,
  '',
)

/** A failed API call, with a message written for the person using the app. */
export class ApiError extends Error {
  readonly status: number
  /** Messages for individual fields, from 422 validation errors (keyed by field name). */
  readonly fieldErrors: Readonly<Record<string, string>>
  /** The same messages keyed by their full path in the body, e.g. "metrics.3.reference_low". */
  readonly pathErrors: Readonly<Record<string, string>>
  /** The response's `detail`, for errors that carry data (e.g. the existing report's id). */
  readonly detail: unknown

  constructor(
    status: number,
    message: string,
    fieldErrors: Record<string, string> = {},
    pathErrors: Record<string, string> = {},
    detail: unknown = null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.fieldErrors = fieldErrors
    this.pathErrors = pathErrors
    this.detail = detail
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

/** Turn an error response's status and parsed JSON body into an ApiError. */
function errorFromBody(status: number, body: unknown): ApiError {
  const detail =
    typeof body === 'object' && body !== null && 'detail' in body ? body.detail : undefined
  if (typeof detail === 'string') return new ApiError(status, detail, {}, {}, detail)
  if (Array.isArray(detail)) {
    const fieldErrors: Record<string, string> = {}
    const pathErrors: Record<string, string> = {}
    for (const issue of detail as ValidationIssue[]) {
      if (!issue.msg || !Array.isArray(issue.loc)) continue
      const message = issue.msg.replace(/^Value error, /, '')
      const path = issue.loc.filter((part, index) => !(index === 0 && part === 'body'))
      const field = path.at(-1)
      if (typeof field === 'string' && !(field in fieldErrors)) fieldErrors[field] = message
      const key = path.join('.')
      if (key && !(key in pathErrors)) pathErrors[key] = message
    }
    return new ApiError(status, 'Some details need fixing.', fieldErrors, pathErrors, detail)
  }
  if (typeof detail === 'object' && detail !== null && 'message' in detail) {
    return new ApiError(status, String(detail.message), {}, {}, detail)
  }
  return new ApiError(
    status,
    status >= 500
      ? 'Something went wrong on the server. Try again in a minute.'
      : `The request failed (${status}).`,
  )
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown
  } catch {
    return null // not JSON (e.g. a proxy error page)
  }
}

/** The token to send, ending a session whose token has expired. */
function currentToken(): string | undefined {
  const current = session.get()
  // The expiry timer can fire late (e.g. after the computer sleeps): end the session now.
  if (current !== null && current.expiresAt <= Date.now()) session.clear()
  return session.get()?.token
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  json?: unknown
  signal?: AbortSignal
  accept?: string
}

/** Send a request with the session's token; return the response if it succeeded. */
async function send(path: string, options: RequestOptions = {}): Promise<Response> {
  const token = currentToken()
  const headers: Record<string, string> = { Accept: options.accept ?? 'application/json' }
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
  if (!response.ok) throw errorFromBody(response.status, parseJson(await response.text()))
  return response
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

async function requestBlob(path: string, accept: string): Promise<Blob> {
  return (await send(path, { accept })).blob()
}

// --- uploads -------------------------------------------------------------------------------

/** Matches the backend's default MAX_UPLOAD_MB; the server enforces its own limit too. */
export const MAX_UPLOAD_MB = 10

export const UPLOAD_NETWORK_ERROR =
  "The upload didn't finish. Check your internet connection and try again."

/** Upload a PDF as the raw request body. Uses XMLHttpRequest because fetch cannot report
 * upload progress; `onProgress` receives a fraction from 0 to 1. */
export function uploadReport(
  memberId: string,
  file: Blob,
  onProgress?: (fraction: number) => void,
): Promise<Report> {
  return new Promise((resolve, reject) => {
    const token = currentToken()
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE_URL}/patients/${memberId}/reports`)
    xhr.setRequestHeader('Content-Type', 'application/pdf')
    xhr.setRequestHeader('Accept', 'application/json')
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress?.(event.loaded / event.total)
    }
    xhr.onload = () => {
      const body = parseJson(xhr.responseText)
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as Report)
        return
      }
      if (xhr.status === 401 && token) session.clear()
      reject(errorFromBody(xhr.status, body))
    }
    xhr.onerror = () => {
      reject(new ApiError(0, UPLOAD_NETWORK_ERROR))
    }
    xhr.send(file)
  })
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

  reports: (memberId: string) => request<ReportSummary[]>(`/patients/${memberId}/reports`),
  report: (id: string) => request<Report>(`/reports/${id}`),
  review: (id: string) => request<ReportReview>(`/reports/${id}/review`),
  confirmReport: (id: string, input: ConfirmReportInput) =>
    request<Report>(`/reports/${id}/confirm`, { method: 'POST', json: input }),
  retryReport: (id: string) => request<Report>(`/reports/${id}/retry`, { method: 'POST' }),
  deleteReport: (id: string) => request<undefined>(`/reports/${id}`, { method: 'DELETE' }),
  reportFile: (id: string) => requestBlob(`/reports/${id}/file`, 'application/pdf'),
  reportReadings: (id: string) => request<Reading[]>(`/reports/${id}/metrics`),
  metricDictionary: () => request<MetricDefinition[]>('/metric-dictionary'),

  catalog: (memberId: string) => request<CatalogEntry[]>(`/patients/${memberId}/metrics`),
  metricHistory: (memberId: string, metricId: string) =>
    request<MetricHistory>(`/patients/${memberId}/metrics/${metricId}`),
  familyOverview: (familyId: string) => request<FamilyOverview>(`/families/${familyId}/overview`),
}
