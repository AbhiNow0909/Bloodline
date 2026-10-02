/**
 * An in-memory stand-in for the Bloodline API, installed as `fetch` and `XMLHttpRequest`
 * (uploads). It keeps families, members and reports like the real backend does (ordering,
 * counts, 401/404/409/204 responses, report statuses), so tests can walk through whole flows.
 * All names and values here are made up.
 */
import { vi } from 'vitest'

import type {
  CatalogEntry,
  ChatMessage,
  ChatReply,
  ConfirmReportInput,
  Family,
  Insight,
  InsightResult,
  Member,
  MemberInput,
  MetricInfo,
  Reading,
  Report,
  ReportReview,
  ReportSummary,
  User,
} from '../lib/types'
import { parseNumber, previewFlag } from '../lib/values'
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

export const DISCLAIMER =
  'Not medical advice. Bloodline can describe your results, but only your doctor can say what they mean for you.'

const json = (status: number, body?: unknown): Reply => ({ status, body })
const notFound = (what: string) => json(404, { detail: `${what} not found` })

export function fakeApi() {
  const families = new Map<string, Omit<Family, 'patient_count'>>()
  const members = new Map<string, Member>()
  const reports = new Map<string, FakeReport>()
  const calls: Call[] = []
  const overrides: ((call: Call) => Reply | undefined)[] = []
  const chatAnswers: string[] = []
  const explainAnswers: string[] = []
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
      value_numeric: parseNumber(row.value_text),
      unit: row.unit,
      value_canonical: row.canonical_metric_id ? parseNumber(row.value_text) : null,
      unit_canonical: row.canonical_metric_id ? row.unit : null,
      reference_low: row.reference_low,
      reference_high: row.reference_high,
      reference_text: row.reference_text,
      flag: previewFlag(row.value_text, row.reference_low, row.reference_high),
    }))
    Object.assign(report, { status: 'confirmed', collected_at: collectedAt })
    entry.review = null
    return json(200, report)
  }

  // --- history, derived from confirmed readings like the backend does ---

  const metricInfo = (id: string | null): MetricInfo | null => {
    const found = DICTIONARY.find((d) => d.id === id)
    return found
      ? {
          id: found.id,
          canonical_name: found.canonical_name,
          category: found.category,
          canonical_unit: found.canonical_unit,
          description: found.description,
        }
      : null
  }
  const readingsOf = (memberIds: string[]) =>
    [...reports.values()]
      .filter((r) => r.report.status === 'confirmed' && memberIds.includes(r.report.patient_id))
      .flatMap((r) => r.readings)
  const seriesOf = (r: Reading) => r.canonical_metric_id ?? `raw:${r.raw_name}`
  const byTime = (a: Reading, b: Reading) => Date.parse(a.collected_at) - Date.parse(b.collected_at)
  const nameOf = (r: Reading) => metricInfo(r.canonical_metric_id)?.canonical_name ?? r.raw_name
  const byCategoryAndName = (a: Reading, b: Reading) => {
    const ca = metricInfo(a.canonical_metric_id)?.category
    const cb = metricInfo(b.canonical_metric_id)?.category
    if ((ca === undefined) !== (cb === undefined)) return ca === undefined ? 1 : -1
    return (ca ?? '').localeCompare(cb ?? '') || nameOf(a).localeCompare(nameOf(b))
  }

  /** The latest reading of each test, per member. */
  function latestPerSeries(memberIds: string[]): Reading[] {
    const latest = new Map<string, Reading>()
    for (const reading of readingsOf(memberIds).sort(byTime)) {
      latest.set(`${reading.patient_id}|${seriesOf(reading)}`, reading)
    }
    return [...latest.values()].sort(byCategoryAndName)
  }

  function catalog(memberId: string): CatalogEntry[] {
    const all = readingsOf([memberId]).sort(byTime)
    return latestPerSeries([memberId]).map((latest) => {
      const series = all.filter((r) => seriesOf(r) === seriesOf(latest))
      return {
        metric: metricInfo(latest.canonical_metric_id),
        name: nameOf(latest),
        reading_count: series.length,
        first_collected_at: series[0]?.collected_at ?? latest.collected_at,
        latest,
      }
    })
  }

  /** What a member's results show, like the server works it out (`insights/rules.py`):
   * outside the range, back within it, or a change of 25 % or more across the last 3. */
  function insightsOf(memberId: string): Insight[] {
    const series = new Map<string, Reading[]>()
    for (const reading of readingsOf([memberId]).sort(byTime)) {
      if (!reading.canonical_metric_id) continue
      series.set(reading.canonical_metric_id, [
        ...(series.get(reading.canonical_metric_id) ?? []),
        reading,
      ])
    }
    const result = (r: Reading): InsightResult => ({
      report_id: r.report_id,
      collected_at: r.collected_at,
      value_text: r.value_text,
      unit: r.unit,
      value_canonical: r.value_canonical,
      flag: r.flag,
    })
    const decimals = (v: string) => v.split('.')[1]?.length ?? 0
    const found: { insight: Insight; rank: number }[] = []
    for (const [metricId, points] of series) {
      const metric = metricInfo(metricId)
      const latest = points.at(-1)
      if (!metric || !latest) continue
      const previous = points.at(-2)
      const make = (
        kind: Insight['kind'],
        compared: Reading | undefined,
        resultsCompared: number,
        inARow = 0,
      ): Insight => {
        let change: string | null = null
        let percent: number | null = null
        if (compared?.value_canonical && latest.value_canonical) {
          const [a, b] = [Number(compared.value_canonical), Number(latest.value_canonical)]
          change = (b - a).toFixed(
            Math.max(decimals(compared.value_canonical), decimals(latest.value_canonical)),
          )
          percent = a === 0 ? null : Math.round(((b - a) / Math.abs(a)) * 1000) / 10
        }
        return {
          patient_id: memberId,
          kind,
          metric,
          latest: result(latest),
          compared_with: compared ? result(compared) : null,
          results_compared: resultsCompared,
          change,
          percent_change: percent,
          outside_in_a_row: inARow,
          reference_low: latest.reference_low,
          reference_high: latest.reference_high,
        }
      }
      if (latest.flag === 'low' || latest.flag === 'high') {
        let inARow = 0
        for (const point of [...points].reverse()) {
          if (point.flag !== latest.flag) break
          inARow++
        }
        const newly = previous !== undefined && previous.flag !== latest.flag
        found.push({
          insight: make('outside_range', previous, previous ? 2 : 1, inARow),
          rank: newly ? 0 : 1,
        })
      } else if (latest.flag === 'normal' && previous) {
        if (previous.flag === 'low' || previous.flag === 'high') {
          found.push({ insight: make('back_in_range', previous, 2), rank: 3 })
        } else {
          const window = points.filter((p) => p.value_canonical !== null).slice(-3)
          const first = window[0]
          const change =
            window.length > 1 && first ? make('big_change', first, window.length) : null
          if (change?.percent_change != null && Math.abs(change.percent_change) >= 25) {
            found.push({ insight: change, rank: 2 })
          }
        }
      }
    }
    return found
      .sort(
        (a, b) =>
          a.rank - b.rank ||
          a.insight.metric.category.localeCompare(b.insight.metric.category) ||
          a.insight.metric.canonical_name.localeCompare(b.insight.metric.canonical_name),
      )
      .map((f) => f.insight)
  }

  function overview(familyId: string, name: string) {
    const list = [...members.values()]
      .filter((m) => m.family_id === familyId)
      .sort((a, b) => a.display_name.localeCompare(b.display_name))
    return {
      family_id: familyId,
      name,
      members: list.map((patient) => {
        const latest = latestPerSeries([patient.id])
        const times = readingsOf([patient.id])
          .map((r) => r.collected_at)
          .sort()
        return {
          patient,
          latest_report_at: times.at(-1) ?? null,
          tracked_metric_count: latest.length,
          out_of_range: latest
            .filter((r) => r.flag === 'low' || r.flag === 'high')
            .map((r) => ({
              ...r,
              name: nameOf(r),
              category: metricInfo(r.canonical_metric_id)?.category ?? null,
            })),
          insights: insightsOf(patient.id),
        }
      }),
    }
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

  /** Like the real agent: an answer, the saved reports it read, and the disclaimer. Answers
   * come from `answerChat`, else echo the question. */
  function chat(call: Call, memberIds: string[]): Reply {
    const { messages } = call.body as { messages: ChatMessage[] }
    const question = messages.at(-1)?.content ?? ''
    const sources = [...reports.values()]
      .filter((r) => r.report.status === 'confirmed' && memberIds.includes(r.report.patient_id))
      .map(({ report }) => {
        const member = members.get(report.patient_id)
        return {
          report_id: report.id,
          collected_at: report.collected_at ?? report.created_at,
          lab_name: report.lab_name,
          member_id: report.patient_id,
          member_name: member?.display_name ?? '',
        }
      })
    const reply: ChatReply = {
      reply: chatAnswers.shift() ?? `You asked: ${question}`,
      sources,
      disclaimer: DISCLAIMER,
    }
    return json(200, reply)
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

    match = /^\/families\/([^/]+)\/chat$/.exec(path)
    if (match?.[1] && method === 'POST') {
      const familyId = match[1]
      if (!families.has(familyId)) return notFound('Family')
      const ids = [...members.values()].filter((m) => m.family_id === familyId).map((m) => m.id)
      if (ids.length === 0) {
        return json(409, { detail: 'Add a family member before asking about this family.' })
      }
      return chat(call, ids)
    }

    match = /^\/patients\/([^/]+)\/insights(\/explain)?$/.exec(path)
    if (match?.[1]) {
      const memberId = match[1]
      if (!members.has(memberId)) return notFound('Patient')
      const found = insightsOf(memberId)
      if (!match[2]) return json(200, found)
      return json(200, {
        explanations: found.map((insight) => ({
          metric_id: insight.metric.id,
          kind: insight.kind,
          text: explainAnswers.shift() ?? `${insight.metric.canonical_name}, explained simply.`,
        })),
        disclaimer: DISCLAIMER,
      })
    }

    match = /^\/patients\/([^/]+)\/chat$/.exec(path)
    if (match?.[1] && method === 'POST') {
      return members.has(match[1]) ? chat(call, [match[1]]) : notFound('Patient')
    }

    match = /^\/families\/([^/]+)\/overview$/.exec(path)
    if (match?.[1]) {
      const family = families.get(match[1])
      return family ? json(200, overview(family.id, family.name)) : notFound('Family')
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

    match = /^\/patients\/([^/]+)\/metrics(?:\/([^/]+))?$/.exec(path)
    if (match?.[1]) {
      const memberId = match[1]
      if (!members.has(memberId)) return notFound('Patient')
      const metricId = match[2]
      if (!metricId) return json(200, catalog(memberId))
      const metric = metricInfo(metricId)
      if (!metric) return notFound('Metric')
      const points = readingsOf([memberId])
        .filter((r) => r.canonical_metric_id === metricId)
        .sort(byTime)
        .map((r) => ({
          ...r,
          reference_low_canonical: r.reference_low,
          reference_high_canonical: r.reference_high,
        }))
      return json(200, { metric, points })
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
    // A held AI request (chat or explanations) waits here until the test releases it.
    if (chatGate && (call.path.endsWith('/chat') || call.path.endsWith('/explain'))) {
      const reply = chatGate.then(() => respond(call))
      lastChat = reply.then(() => undefined)
      return reply
    }
    return Promise.resolve(respond(call))
  })
  vi.stubGlobal('fetch', fetchMock)

  let chatGate: Promise<void> | null = null
  let lastChat: Promise<void> = Promise.resolve()
  function respond(call: Call): Response {
    const reply = route(call)
    if (reply.file) {
      return new Response(reply.file, {
        status: reply.status,
        headers: { 'Content-Type': reply.file.type },
      })
    }
    const text = reply.body === undefined ? null : JSON.stringify(reply.body)
    return new Response(text, {
      status: reply.status,
      headers: text === null ? {} : { 'Content-Type': 'application/json' },
    })
  }

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
    /** The assistant's next answers, in order (otherwise it echoes the question). */
    answerChat(...answers: string[]) {
      chatAnswers.push(...answers)
    },
    /** The AI's next explanations, in order (otherwise "<test>, explained simply."). */
    explainWith(...texts: string[]) {
      explainAnswers.push(...texts)
    },
    /** Hold AI requests (chat and explanations) until the returned function is called. */
    holdAi() {
      let release = () => {}
      chatGate = new Promise((resolve) => {
        release = () => {
          chatGate = null
          resolve()
        }
      })
      return release
    },
    /** Settles once the latest held AI request has been answered. */
    answered: () => lastChat,
    /** The messages each chat question sent, oldest first. */
    chatRequests: () =>
      calls
        .filter((c) => c.path.endsWith('/chat'))
        .map((c) => (c.body as { messages: ChatMessage[] }).messages),
    /** Answer matching calls differently (e.g. with an error); return undefined to pass. */
    override(handler: (call: Call) => Reply | undefined) {
      overrides.push(handler)
    },
    /** Calls other than the ones every signed-in page makes (e.g. GET /auth/me). */
    writes: () => calls.filter((c) => c.method !== 'GET'),
  }
}
