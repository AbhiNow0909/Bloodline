import { QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, useSyncExternalStore } from 'react'

import { ApiError, api, uploadReport } from './api'
import { objectUrlFor, releaseObjectUrlsWith } from './objectUrls'
import { session, type Session } from './session'
import type {
  ConfirmReportInput,
  Family,
  Member,
  MemberInput,
  Report,
  ReportSummary,
} from './types'

export function createQueryClient(): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // Retry only server-side failures; a 404 or 401 will not change on its own.
        retry: (count, error) => error instanceof ApiError && error.status >= 500 && count < 2,
      },
    },
  })
  releaseObjectUrlsWith(client)
  return client
}

export function useSession(): Session | null {
  return useSyncExternalStore(session.subscribe, session.get, session.get)
}

/** Forget every cached family, member and result when the user signs out (or the session
 * changes to another account), so nothing of theirs is shown to whoever signs in next. */
export function clearCacheOnSessionChange(client: QueryClient): () => void {
  let token = session.get()?.token
  return session.subscribe(() => {
    const next = session.get()?.token
    if (token !== undefined && next !== token) client.clear()
    token = next
  })
}

export const keys = {
  me: ['me'] as const,
  families: ['families'] as const,
  family: (id: string) => ['families', id] as const,
  members: (familyId: string) => ['families', familyId, 'members'] as const,
  member: (id: string) => ['members', id] as const,
  reports: (memberId: string) => ['members', memberId, 'reports'] as const,
  report: (id: string) => ['reports', id] as const,
  review: (id: string) => ['reports', id, 'review'] as const,
  readings: (id: string) => ['reports', id, 'readings'] as const,
  reportFile: (id: string) => ['reports', id, 'file'] as const,
  dictionary: ['metric-dictionary'] as const,
  catalog: (memberId: string) => ['members', memberId, 'catalog'] as const,
  metricHistory: (memberId: string, metricId: string) =>
    ['members', memberId, 'history', metricId] as const,
  familyOverview: (familyId: string) => ['families', familyId, 'overview'] as const,
}

/** How often a report being read is checked again. Tests shorten it. */
export const polling = { intervalMs: 2_000 }

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: api.me })
export const useFamilies = () => useQuery({ queryKey: keys.families, queryFn: api.families })
export const useFamily = (id: string) =>
  useQuery({ queryKey: keys.family(id), queryFn: () => api.family(id) })
export const useMembers = (familyId: string) =>
  useQuery({ queryKey: keys.members(familyId), queryFn: () => api.members(familyId) })
export const useMember = (id: string) =>
  useQuery({ queryKey: keys.member(id), queryFn: () => api.member(id) })

export function useCreateFamily() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.createFamily,
    onSuccess: (family) => {
      client.setQueryData(keys.family(family.id), family)
      return client.invalidateQueries({ queryKey: keys.families, exact: true })
    },
  })
}

export function useRenameFamily(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.renameFamily(id, name),
    onSuccess: (family) => {
      client.setQueryData(keys.family(id), family)
      return client.invalidateQueries({ queryKey: keys.families, exact: true })
    },
  })
}

export function useDeleteFamily(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.deleteFamily(id),
    onSuccess: () => {
      client.setQueryData<Family[]>(keys.families, (old) => old?.filter((f) => f.id !== id))
      return markDeleted(client)
    },
  })
}

/** Everything under ['families']: the list and its member counts, each family, and every
 * family's member list. */
function refreshFamilies(client: QueryClient) {
  return client.invalidateQueries({ queryKey: keys.families })
}

/** After a delete, mark every family and member query stale *without* refetching the ones on
 * screen: the page that showed the deleted item is about to navigate away, and refetching it
 * now would only return 404. Pages mounted later refetch, so a deleted family or member
 * opened again (e.g. with Back) shows "not found" instead of cached data. */
function markDeleted(client: QueryClient) {
  return Promise.all([
    client.invalidateQueries({ queryKey: keys.families, refetchType: 'none' }),
    client.invalidateQueries({ queryKey: ['members'], refetchType: 'none' }),
  ])
}

export function useAddMember(familyId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: MemberInput) => api.addMember(familyId, input),
    onSuccess: () => refreshFamilies(client),
  })
}

export function useUpdateMember(id: string, familyId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: Partial<MemberInput>) => api.updateMember(id, input),
    onSuccess: (member) => {
      client.setQueryData(keys.member(id), member)
      return client.invalidateQueries({ queryKey: keys.members(familyId) })
    },
  })
}

export function useDeleteMember(id: string, familyId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.deleteMember(id),
    onSuccess: () => {
      client.setQueryData<Member[]>(keys.members(familyId), (old) =>
        old?.filter((m) => m.id !== id),
      )
      return markDeleted(client)
    },
  })
}

// --- reports -------------------------------------------------------------------------------

const isProcessing = (report: Report | undefined) => report?.status === 'processing'

/** A member's reports; checked again every few seconds while any is still being read. */
export const useReports = (memberId: string) =>
  useQuery({
    queryKey: keys.reports(memberId),
    queryFn: () => api.reports(memberId),
    refetchInterval: (query) => (query.state.data?.some(isProcessing) ? polling.intervalMs : false),
  })

/** One report's status; checked again every few seconds while it is being read. */
export const useReport = (id: string) =>
  useQuery({
    queryKey: keys.report(id),
    queryFn: () => api.report(id),
    refetchInterval: (query) => (isProcessing(query.state.data) ? polling.intervalMs : false),
  })

/** The extracted rows. Loaded once: refetching would not change them, and the review form
 * keeps its own edited copy. */
export const useReview = (id: string, enabled: boolean) =>
  useQuery({
    queryKey: keys.review(id),
    queryFn: () => api.review(id),
    enabled,
    staleTime: Infinity,
  })

export const useReadings = (id: string, enabled: boolean) =>
  useQuery({ queryKey: keys.readings(id), queryFn: () => api.reportReadings(id), enabled })

/** Every test the app knows; it only changes when the backend is re-seeded. */
export const useMetricDictionary = () =>
  useQuery({ queryKey: keys.dictionary, queryFn: api.metricDictionary, staleTime: Infinity })

/** The original PDF as a local object URL (fetched with the session's token; the file never
 * leaves this browser). Kept for a minute after it is last shown, then released. */
export function useReportFileUrl(id: string) {
  const file = useQuery({
    queryKey: keys.reportFile(id),
    queryFn: () => api.reportFile(id),
    staleTime: Infinity,
    gcTime: 60_000,
  })
  return {
    url: file.data ? objectUrlFor(file.data) : null,
    isError: file.isError,
    error: file.error,
  }
}

/** Put a report's new state into the cache, and refresh everything built from the member's
 * reports: their report list, results and charts, and the family overviews. */
function reportChanged(client: QueryClient, report: Report) {
  client.setQueryData(keys.report(report.id), report)
  return historyChanged(client, report.patient_id)
}

function historyChanged(client: QueryClient, memberId: string) {
  return Promise.all([
    client.invalidateQueries({
      queryKey: ['members', memberId],
      // The member's own details did not change.
      predicate: (query) => query.queryKey.length > 2,
    }),
    client.invalidateQueries({
      predicate: (query) => query.queryKey[0] === 'families' && query.queryKey[2] === 'overview',
    }),
  ])
}

/** Upload a PDF; `progress` is 0–1 while the file is being sent. */
export function useUploadReport(memberId: string) {
  const client = useQueryClient()
  const [progress, setProgress] = useState(0)
  const mutation = useMutation({
    mutationFn: (file: Blob) => {
      setProgress(0)
      return uploadReport(memberId, file, setProgress)
    },
    onSuccess: (report) => reportChanged(client, report),
  })
  return { ...mutation, progress }
}

export function useConfirmReport(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: ConfirmReportInput) => api.confirmReport(id, input),
    onSuccess: (report) => {
      client.removeQueries({ queryKey: keys.review(id) })
      return reportChanged(client, report)
    },
  })
}

export function useRetryReport(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.retryReport(id),
    onSuccess: (report) => reportChanged(client, report),
  })
}

export function useDeleteReport(report: Pick<Report, 'id' | 'patient_id'>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.deleteReport(report.id),
    onSuccess: () => {
      client.setQueryData<ReportSummary[]>(keys.reports(report.patient_id), (old) =>
        old?.filter((r) => r.id !== report.id),
      )
      return Promise.all([
        historyChanged(client, report.patient_id),
        client.invalidateQueries({ queryKey: keys.report(report.id), refetchType: 'none' }),
      ])
    },
  })
}

// --- history -------------------------------------------------------------------------------

/** Every test the member has results for, with its latest value. */
export const useCatalog = (memberId: string) =>
  useQuery({ queryKey: keys.catalog(memberId), queryFn: () => api.catalog(memberId) })

/** One test's results over time, for its chart. */
export const useMetricHistory = (memberId: string, metricId: string) =>
  useQuery({
    queryKey: keys.metricHistory(memberId, metricId),
    queryFn: () => api.metricHistory(memberId, metricId),
  })

/** Each member's latest out-of-range values, side by side. */
export const useFamilyOverview = (familyId: string) =>
  useQuery({
    queryKey: keys.familyOverview(familyId),
    queryFn: () => api.familyOverview(familyId),
  })
