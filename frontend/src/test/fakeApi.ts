/**
 * An in-memory stand-in for the Bloodline API, installed as `fetch` and `XMLHttpRequest`
 * (uploads). It keeps families, members and reports like the real backend does (ordering,
 * counts, 401/404/409/204 responses, report statuses), so tests can walk through whole flows.
 * All names and values here are made up.
 */
import { vi } from 'vitest'

import type {
  ConfirmReportInput,
  Family,
  Member,
  MemberInput,
  Reading,
  Report,
  ReportReview,
  ReportSummary,
  User,
} from '../lib/types'
import { previewFlag } from '../lib/values'
import { DICTIONARY, sampleReview } from './reportData'
import { fakeToken } from './session'

export interface Call {
  method: string
  path: string
  body: unknown
  authorization: string | null
  contentType?: string | null
}

export interface Reply {
  status: number
  body?: unknown
  /** A file instead of JSON (e.g. the report PDF). */
  file?: Blob
}

interface FakeReport {
  report: Report
  review: Omit<ReportReview, 'report'> | null
  readings: Reading[]
  content: string
  confirmed?: ConfirmReportInput
}

export const USER: User = { id: 'user-1', email: 'asha@example.com', display_name: 'Asha Rao' }
export const PASSWORD = 'correct horse battery staple'

const json = (status: number, body?: unknown): Reply => ({ status, body })
const notFound = (what: string) => json(404, { detail: `${what} not found` })

export function fakeApi() {
  const families = new Map<string, Omit<Family, 'patient_count'>>()
  const members = new Map<string, Member>()
  const reports = new Map<string, FakeReport>()
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

  function addReport(
    memberId: string,
    fields: Partial<Report> = {},
    review: Omit<ReportReview, 'report'> | null = null,
    readings: Reading[] = [],
  ): Report {
    const report: Report = {
      id: newId('report'),
      patient_id: memberId,
      status: 'processing',
      lab_name: null,
      collected_at: null,
      failure_reason: null,
      created_at: '2026-09-29T04:30:00Z',
      ...fields,
    }
    reports.set(report.id, { report, review, readings, content: report.id })
    return report
  }

  function reportOf(id: string): FakeReport {
    const found = reports.get(id)
    if (!found) throw new Error(`no fake report ${id}`)
    return found
  }

  /** Background processing finished: the report now waits for review. */
  function finishProcessing(
    id: string,
    fields: Partial<Report> = { lab_name: 'Example Labs', collected_at: '2026-09-28T02:35:00Z' },
    review: Omit<ReportReview, 'report'> = sampleReview(),
  ) {
    const entry = reportOf(id)
    Object.assign(entry.report, { status: 'pending_review', ...fields })
    entry.review = review
  }

  function failProcessing(id: string, reason: string) {
    Object.assign(reportOf(id).report, { status: 'failed', failure_reason: reason })
  }

  function summary({ report, readings }: FakeReport): ReportSummary {
    return {
      ...report,
      metric_count: readings.length,
      flagged_count: readings.filter((r) => r.flag === 'low' || r.flag === 'high').length,
    }
  }

  function confirm(entry: FakeReport, input: ConfirmReportInput): Reply {
    const { report } = entry
    if (report.status !== 'pending_review') {
      return json(409, {
        detail: `This report is not waiting for review (status: ${report.status}).`,
      })
    }
    const collectedAt = input.collected_at ?? report.collected_at
    if (!collectedAt) {
      return json(422, {
        detail: 'The collection date could not be read from the report; enter it.',
      })
    }
    entry.confirmed = input
    entry.readings = input.metrics.map((row) => ({
      patient_id: report.patient_id,
      report_id: report.id,
      collected_at: collectedAt,
      canonical_metric_id: row.canonical_metric_id,
      raw_name: row.raw_name,
      value_text: row.value_text,
      value_numeric: null,
      unit: row.unit,
      value_canonical: null,
      unit_canonical: null,
      reference_low: row.reference_low,
      reference_high: row.reference_high,
      reference_text: row.reference_text,
      flag: previewFlag(row.value_text, row.reference_low, row.reference_high),
    }))
    Object.assign(report, { status: 'confirmed', collected_at: collectedAt })
    entry.review = null
    return json(200, report)
  }

  /** POST /patients/{id}/reports, sent through the fake XMLHttpRequest. */
  function upload(call: Call, memberId: string, content: string): Reply {
    if (!members.has(memberId)) return notFound('Patient')
    if (call.contentType !== 'application/pdf') {
      return json(415, {
        detail: 'Send the PDF as the request body with Content-Type: application/pdf.',
      })
    }
    const existing = [...reports.values()].find(
      (r) => r.report.patient_id === memberId && r.content === content,
    )
    if (existing) {
      return json(409, {
        detail: {
          message: 'This report was already uploaded for this family member.',
          report_id: existing.report.id,
        },
      })
    }
    const report = addReport(memberId, { created_at: new Date().toISOString() })
    reportOf(report.id).content = content
    return json(202, report)
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

    match = /^\/patients\/([^/]+)\/reports$/.exec(path)
    if (match?.[1]) {
      const memberId = match[1]
      if (method === 'POST') return upload(call, memberId, (body as { content: string }).content)
      if (!members.has(memberId)) return notFound('Patient')
      const list = [...reports.values()].filter((r) => r.report.patient_id === memberId)
      return json(200, list.map(summary).reverse())
    }

    if (method === 'GET' && path === '/metric-dictionary') return json(200, DICTIONARY)

    match = /^\/reports\/([^/]+)(?:\/(review|confirm|retry|file|metrics))?$/.exec(path)
    if (match?.[1]) {
      const entry = reports.get(match[1])
      if (!entry) return notFound('Report')
      const action = match[2]
      const { report } = entry
      if (!action && method === 'GET') return json(200, report)
      if (!action && method === 'DELETE') {
        reports.delete(report.id)
        return json(204)
      }
      if (action === 'review') {
        return report.status === 'pending_review' && entry.review
          ? json(200, { report, ...entry.review })
          : json(409, {
              detail: `This report is not waiting for review (status: ${report.status}).`,
            })
      }
      if (action === 'confirm') return confirm(entry, call.body as ConfirmReportInput)
      if (action === 'retry') {
        if (report.status !== 'failed')
          return json(409, { detail: 'Only failed reports can be retried.' })
        Object.assign(report, { status: 'processing', failure_reason: null })
        return json(202, report)
      }
      if (action === 'file') {
        return { status: 200, file: new Blob(['%PDF-1.4 synthetic'], { type: 'application/pdf' }) }
      }
      if (action === 'metrics') return json(200, entry.readings)
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
    if (reply.file) {
      return Promise.resolve(
        new Response(reply.file, {
          status: reply.status,
          headers: { 'Content-Type': reply.file.type },
        }),
      )
    }
    const text = reply.body === undefined ? null : JSON.stringify(reply.body)
    return Promise.resolve(
      new Response(text, {
        status: reply.status,
        headers: text === null ? {} : { 'Content-Type': 'application/json' },
      }),
    )
  })
  vi.stubGlobal('fetch', fetchMock)

  // Uploads: a minimal XMLHttpRequest that reports progress, then answers through `route`.
  let uploadGate: Promise<void> | null = null
  let uploadFails = false
  class FakeXMLHttpRequest {
    upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null }
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    status = 0
    responseText = ''
    private method = 'GET'
    private url = ''
    private readonly headers = new Headers()

    open(method: string, url: string) {
      this.method = method
      this.url = url
    }

    setRequestHeader(name: string, value: string) {
      this.headers.set(name, value)
    }

    send(file: Blob) {
      const total = file.size
      const progress = (loaded: number) => {
        this.upload.onprogress?.({ lengthComputable: true, loaded, total } as ProgressEvent)
      }
      void (async () => {
        await Promise.resolve()
        progress(Math.floor(total / 2))
        if (uploadGate) await uploadGate
        if (uploadFails) {
          this.onerror?.()
          return
        }
        progress(total)
        const call: Call = {
          method: this.method,
          path: new URL(this.url).pathname,
          body: {
            name: file instanceof File ? file.name : 'blob',
            size: total,
            content: await file.text(),
          },
          authorization: this.headers.get('Authorization'),
          contentType: this.headers.get('Content-Type'),
        }
        calls.push(call)
        const reply = route(call)
        this.status = reply.status
        this.responseText = reply.body === undefined ? '' : JSON.stringify(reply.body)
        this.onload?.()
      })()
    }
  }
  vi.stubGlobal('XMLHttpRequest', FakeXMLHttpRequest)

  return {
    calls,
    families,
    members,
    reports,
    addFamily,
    addMember,
    addReport,
    finishProcessing,
    failProcessing,
    /** The body the last confirm of a report sent. */
    confirmed: (id: string) => reportOf(id).confirmed,
    /** Hold uploads at 50% until the returned function is called. */
    holdUploads() {
      let release = () => {}
      uploadGate = new Promise((resolve) => {
        release = () => {
          uploadGate = null
          resolve()
        }
      })
      return release
    },
    /** Make uploads fail as if the connection dropped. */
    failUploads() {
      uploadFails = true
    },
    /** Answer matching calls differently (e.g. with an error); return undefined to pass. */
    override(handler: (call: Call) => Reply | undefined) {
      overrides.push(handler)
    },
    /** Calls other than the ones every signed-in page makes (e.g. GET /auth/me). */
    writes: () => calls.filter((c) => c.method !== 'GET'),
  }
}
