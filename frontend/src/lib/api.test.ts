import { describe, expect, it, vi } from 'vitest'

import { fakeToken, signIn } from '../test/session'
import { API_BASE_URL, ApiError, NETWORK_ERROR, errorMessage, request } from './api'
import { session } from './session'

function stubFetch(status: number, body?: unknown) {
  const fetchMock = vi.fn(() =>
    Promise.resolve(new Response(body === undefined ? null : JSON.stringify(body), { status })),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function sentHeaders(fetchMock: ReturnType<typeof stubFetch>): Headers {
  const init = (fetchMock.mock.calls[0] as unknown[] | undefined)?.[1] as RequestInit
  return new Headers(init.headers)
}

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  const error: unknown = await promise.then(
    () => null,
    (e: unknown) => e,
  )
  if (!(error instanceof ApiError)) throw new Error('expected an ApiError')
  return error
}

describe('request', () => {
  it('sends JSON with the bearer token of the current session', async () => {
    signIn()
    const fetchMock = stubFetch(201, { id: 'f1' })

    await expect(request('/families', { method: 'POST', json: { name: 'Rao' } })).resolves.toEqual({
      id: 'f1',
    })
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe(`${API_BASE_URL}/families`)
    expect(init.method).toBe('POST')
    expect(init.body).toBe('{"name":"Rao"}')
    const headers = sentHeaders(fetchMock)
    expect(headers.get('Authorization')).toBe(`Bearer ${session.get()?.token ?? ''}`)
    expect(headers.get('Content-Type')).toBe('application/json')
  })

  it('sends no token when signed out', async () => {
    const fetchMock = stubFetch(200, [])
    await request('/families')
    expect(sentHeaders(fetchMock).get('Authorization')).toBeNull()
  })

  it('ends a session whose token has expired instead of sending it', async () => {
    vi.useFakeTimers({ now: new Date('2026-09-30T00:00:00Z'), toFake: ['Date'] })
    session.start(fakeToken(60))
    vi.setSystemTime(new Date('2026-09-30T00:02:00Z')) // the expiry timer has not fired yet
    const fetchMock = stubFetch(200, [])
    await request('/families')
    expect(sentHeaders(fetchMock).get('Authorization')).toBeNull()
    expect(session.get()).toBeNull()
  })

  it('signs out when the server rejects the token', async () => {
    signIn()
    stubFetch(401, { detail: 'Invalid or expired token' })
    const error = await failure(request('/families'))
    expect(error.status).toBe(401)
    expect(session.get()).toBeNull()
  })

  it('returns undefined for 204 No Content', async () => {
    stubFetch(204)
    await expect(request('/families/f1', { method: 'DELETE' })).resolves.toBeUndefined()
  })

  it('uses the server message for string details (404, 409, 401)', async () => {
    stubFetch(409, { detail: 'You already have a family with this name' })
    const error = await failure(request('/families', { method: 'POST', json: { name: 'Rao' } }))
    expect(error.status).toBe(409)
    expect(error.message).toBe('You already have a family with this name')
  })

  it('turns 422 validation errors into per-field messages', async () => {
    stubFetch(422, {
      detail: [
        { loc: ['body', 'date_of_birth'], msg: 'Date should be in the past', type: 'date_past' },
        { loc: ['body', 'sex'], msg: 'Value error, bad sex', type: 'value_error' },
        { loc: ['body', 'sex'], msg: 'second message is ignored', type: 'x' },
      ],
    })
    const error = await failure(request('/patients/p1', { method: 'PATCH', json: {} }))
    expect(error.message).toBe('Some details need fixing.')
    expect(error.fieldErrors).toEqual({
      date_of_birth: 'Date should be in the past',
      sex: 'bad sex',
    })
  })

  it('reads {message} details (e.g. duplicate uploads)', async () => {
    stubFetch(409, { detail: { message: 'Already uploaded', report_id: 'r1' } })
    expect((await failure(request('/x'))).message).toBe('Already uploaded')
  })

  it('gives a plain message for server errors and non-JSON bodies', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('<html>Bad gateway</html>', { status: 502 }))),
    )
    const error = await failure(request('/families'))
    expect(error.status).toBe(502)
    expect(error.message).toBe('Something went wrong on the server. Try again in a minute.')
  })

  it('explains a network failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
    )
    const error = await failure(request('/families'))
    expect(error.status).toBe(0)
    expect(error.message).toBe(NETWORK_ERROR)
  })

  it('lets an abort through unchanged', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new DOMException('The operation was aborted.', 'AbortError'))),
    )
    await expect(request('/families')).rejects.toMatchObject({ name: 'AbortError' })
  })
})

describe('errorMessage', () => {
  it('shows API messages, and a generic one for anything else', () => {
    expect(errorMessage(new ApiError(404, 'Family not found'))).toBe('Family not found')
    expect(errorMessage(new Error('internal detail'))).toBe('Something went wrong. Try again.')
  })
})
