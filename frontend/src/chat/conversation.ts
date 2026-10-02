/**
 * A conversation with the assistant, kept in this browser tab only.
 *
 * The server keeps no chat history, so each question is sent with the last few exchanges.
 * Conversations live in the query cache under their own key: they survive moving around the
 * app for half an hour, and are cleared with everything else when the user signs out.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { api, errorMessage } from '../lib/api'
import type { ChatMessage, ChatReply } from '../lib/types'

export type ChatKind = 'member' | 'family'

export interface Exchange {
  id: string
  question: string
  status: 'waiting' | 'answered' | 'failed'
  reply?: ChatReply
  error?: string
}

/** Earlier exchanges sent with each question: enough context, few tokens (free tier). */
export const HISTORY_EXCHANGES = 4
/** The server's limit for one message. */
export const MAX_MESSAGE_CHARS = 2000

export const chatKey = (kind: ChatKind, id: string) => ['chat', kind, id] as const

let nextId = 0

/** The messages to send for `question`, after the answered exchanges before it. */
export function messagesFor(earlier: Exchange[], question: string): ChatMessage[] {
  const answered = earlier.filter((e) => e.status === 'answered' && e.reply)
  const messages: ChatMessage[] = []
  for (const exchange of answered.slice(-HISTORY_EXCHANGES)) {
    messages.push({ role: 'user', content: exchange.question.slice(0, MAX_MESSAGE_CHARS) })
    messages.push({
      role: 'assistant',
      content: (exchange.reply?.reply ?? '').slice(0, MAX_MESSAGE_CHARS),
    })
  }
  messages.push({ role: 'user', content: question.slice(0, MAX_MESSAGE_CHARS) })
  return messages
}

export function useConversation(kind: ChatKind, id: string) {
  const client = useQueryClient()
  const key = chatKey(kind, id)
  const read = () => client.getQueryData<Exchange[]>(key) ?? []
  const { data: exchanges } = useQuery({
    queryKey: key,
    queryFn: read, // never really fetched: the data is written below
    initialData: [],
    staleTime: Infinity,
    gcTime: 30 * 60_000,
  })

  const update = (change: (list: Exchange[]) => Exchange[]) => {
    client.setQueryData<Exchange[]>(key, (old) => change(old ?? []))
  }
  const send = (messages: ChatMessage[]) =>
    kind === 'member' ? api.memberChat(id, messages) : api.familyChat(id, messages)

  async function run(exchangeId: string, messages: ChatMessage[]) {
    let result: Pick<Exchange, 'status' | 'reply' | 'error'>
    try {
      result = { status: 'answered', reply: await send(messages), error: undefined }
    } catch (error) {
      result = { status: 'failed', error: errorMessage(error), reply: undefined }
    }
    // Matched by id: if the user signed out meanwhile, the cache was cleared and the answer
    // has nowhere to go.
    update((list) => list.map((e) => (e.id === exchangeId ? { ...e, ...result } : e)))
  }

  return {
    exchanges,
    waiting: exchanges.some((e) => e.status === 'waiting'),

    ask(question: string) {
      const text = question.trim()
      if (!text) return Promise.resolve()
      const current = read()
      const exchange: Exchange = { id: `q${String(nextId++)}`, question: text, status: 'waiting' }
      update((list) => [...list, exchange])
      return run(exchange.id, messagesFor(current, text))
    },

    retry(exchangeId: string) {
      const list = read()
      const index = list.findIndex((e) => e.id === exchangeId)
      const exchange = list[index]
      if (!exchange || exchange.status !== 'failed') return Promise.resolve()
      update((all) =>
        all.map((e) => (e.id === exchangeId ? { ...e, status: 'waiting', error: undefined } : e)),
      )
      return run(exchangeId, messagesFor(list.slice(0, index), exchange.question))
    },

    clear() {
      client.setQueryData<Exchange[]>(key, [])
    },
  }
}
