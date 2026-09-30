/**
 * An in-memory stand-in for the Bloodline API, installed as `fetch`. It keeps families and
 * members like the real backend does (ordering, member counts, 401/404/409/204 responses),
 * so tests can walk through whole flows. All names here are made up.
 */
import { vi } from 'vitest'

import type { Family, Member, MemberInput, User } from '../lib/types'
import { fakeToken } from './session'

export interface Call {
  method: string
  path: string
  body: unknown
  authorization: string | null
}

export interface Reply {
  status: number
  body?: unknown
}

export const USER: User = { id: 'user-1', email: 'asha@example.com', display_name: 'Asha Rao' }
export const PASSWORD = 'correct horse battery staple'

const json = (status: number, body?: unknown): Reply => ({ status, body })
const notFound = (what: string) => json(404, { detail: `${what} not found` })

export function fakeApi() {
  const families = new Map<string, Omit<Family, 'patient_count'>>()
  const members = new Map<string, Member>()
  const calls: Call[] = []
  const overrides: ((call: Call) => Reply | undefined)[] = []
  let nextId = 1

  const newId = (prefix: string) => `${prefix}-${String(nextId++)}`
  const countIn = (familyId: string) =>
    [...members.values()].filter((m) => m.family_id === familyId).length
  const withCount = (family: Omit<Family, 'patient_count'>): Family => ({
    ...family,
    patient_count: countIn(family.id),
  })
  const nameTaken = (name: string, exceptId?: string) =>
    [...families.values()].some((f) => f.name === name && f.id !== exceptId)
  const duplicate = json(409, { detail: 'You already have a family with this name' })

  function addFamily(name: string): Family {
    const family = { id: newId('family'), name, created_at: '2026-09-01T10:00:00Z' }
    families.set(family.id, family)
    return withCount(family)
  }

  function addMember(familyId: string, input: MemberInput): Member {
    const member: Member = {
      id: newId('member'),
      family_id: familyId,
      created_at: '2026-09-01T10:00:00Z',
      ...input,
    }
    members.set(member.id, member)
    return member
  }

  function route(call: Call): Reply {
    for (const override of overrides) {
      const reply = override(call)
      if (reply) return reply
    }
    const { method, path } = call
    const body = (call.body ?? {}) as Record<string, unknown>

    if (method === 'POST' && path === '/auth/login') {
      return body.email === USER.email && body.password === PASSWORD
        ? json(200, { access_token: fakeToken(), token_type: 'bearer', expires_in: 3600 })
        : json(401, { detail: 'Invalid email or password' })
    }
    if (call.authorization === null) return json(401, { detail: 'Not authenticated' })
    if (method === 'GET' && path === '/auth/me') return json(200, USER)

    if (path === '/families') {
      if (method === 'GET') {
        const list = [...families.values()].sort((a, b) => a.name.localeCompare(b.name))
        return json(200, list.map(withCount))
      }
      const name = String(body.name).trim()
      return nameTaken(name) ? duplicate : json(201, addFamily(name))
    }

    let match = /^\/families\/([^/]+)$/.exec(path)
    if (match?.[1]) {
      const family = families.get(match[1])
      if (!family) return notFound('Family')
      if (method === 'GET') return json(200, withCount(family))
      if (method === 'PATCH') {
        const name = String(body.name).trim()
        if (nameTaken(name, family.id)) return duplicate
        family.name = name
        return json(200, withCount(family))
      }
      families.delete(family.id)
      for (const member of members.values()) {
        if (member.family_id === family.id) members.delete(member.id)
      }
      return json(204)
    }

    match = /^\/families\/([^/]+)\/patients$/.exec(path)
    if (match?.[1]) {
      const familyId = match[1]
      if (!families.has(familyId)) return notFound('Family')
      if (method === 'GET') {
        const list = [...members.values()].filter((m) => m.family_id === familyId)
        return json(
          200,
          list.sort((a, b) => a.display_name.localeCompare(b.display_name)),
        )
      }
      return json(201, addMember(familyId, body as unknown as MemberInput))
    }

    match = /^\/patients\/([^/]+)$/.exec(path)
    if (match?.[1]) {
      const member = members.get(match[1])
      if (!member) return notFound('Patient')
      if (method === 'GET') return json(200, member)
      if (method === 'PATCH') {
        Object.assign(member, body)
        return json(200, member)
      }
      members.delete(member.id)
      return json(204)
    }

    return json(404, { detail: 'Not Found' })
  }

  const fetchMock = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(input instanceof Request ? input.url : String(input))
    const headers = new Headers(init.headers)
    const call: Call = {
      method: init.method ?? 'GET',
      path: url.pathname,
      body: typeof init.body === 'string' ? (JSON.parse(init.body) as unknown) : undefined,
      authorization: headers.get('Authorization'),
    }
    calls.push(call)
    const reply = route(call)
    const text = reply.body === undefined ? null : JSON.stringify(reply.body)
    return Promise.resolve(
      new Response(text, {
        status: reply.status,
        headers: text === null ? {} : { 'Content-Type': 'application/json' },
      }),
    )
  })
  vi.stubGlobal('fetch', fetchMock)

  return {
    calls,
    families,
    members,
    addFamily,
    addMember,
    /** Answer matching calls differently (e.g. with an error); return undefined to pass. */
    override(handler: (call: Call) => Reply | undefined) {
      overrides.push(handler)
    },
    /** Calls other than the ones every signed-in page makes (e.g. GET /auth/me). */
    writes: () => calls.filter((c) => c.method !== 'GET'),
  }
}
