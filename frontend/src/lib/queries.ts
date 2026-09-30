import { QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'

import { ApiError, api } from './api'
import { session, type Session } from './session'
import type { Family, Member, MemberInput } from './types'

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // Retry only server-side failures; a 404 or 401 will not change on its own.
        retry: (count, error) => error instanceof ApiError && error.status >= 500 && count < 2,
      },
    },
  })
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
}

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
