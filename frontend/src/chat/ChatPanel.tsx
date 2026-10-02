import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type Ref,
  type SubmitEvent,
} from 'react'
import { Link } from 'react-router'

import { Button } from '../components/Button'
import { Icon } from '../components/Icon'
import { formatDate } from '../lib/format'
import type { ChatSource } from '../lib/types'
import { reportPath } from '../reports/labels'
import { parseAnswer, type Span } from './answerText'
import { MAX_MESSAGE_CHARS, useConversation, type ChatKind, type Exchange } from './conversation'

/** After this long, the waiting message explains that the free AI service may be busy. */
const SLOW_AFTER_MS = 8_000

function Spans({ spans }: { spans: Span[] }) {
  return spans.map((span, index) =>
    span.bold ? <strong key={index}>{span.text}</strong> : <span key={index}>{span.text}</span>,
  )
}

function AnswerText({ text }: { text: string }) {
  return (
    <div className="flex max-w-prose flex-col gap-3">
      {parseAnswer(text).map((block, index) => {
        if (block.kind === 'paragraph') {
          return (
            <p key={index}>
              {block.lines.map((line, i) => (
                <span key={i}>
                  {i > 0 && <br />}
                  <Spans spans={line} />
                </span>
              ))}
            </p>
          )
        }
        const List = block.kind === 'bullets' ? 'ul' : 'ol'
        return (
          <List
            key={index}
            className={`flex flex-col gap-1 pl-6 ${block.kind === 'bullets' ? 'list-disc' : 'list-decimal'}`}
          >
            {block.items.map((item, i) => (
              <li key={i}>
                <Spans spans={item} />
              </li>
            ))}
          </List>
        )
      })}
    </div>
  )
}

function Sources({
  sources,
  familyId,
  showMember,
}: {
  sources: ChatSource[]
  familyId: string
  showMember: boolean
}) {
  if (sources.length === 0) return null
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm text-muted">Based on these reports:</p>
      <ul className="flex flex-wrap gap-2">
        {sources.map((source) => (
          <li key={source.report_id}>
            <Link
              to={reportPath(familyId, { id: source.report_id, patient_id: source.member_id })}
              className="group relative inline-flex min-h-11 items-center gap-2 rounded-md border border-line bg-paper py-1.5 pr-6 pl-2.5 text-sm [clip-path:polygon(0_0,calc(100%-0.7rem)_0,100%_0.7rem,100%_100%,0_100%)] hover:border-edta"
            >
              <Icon name="file" className="size-4 text-edta" />
              <span>
                {showMember && (
                  <>
                    <span className="font-semibold">{source.member_name}</span>,{' '}
                  </>
                )}
                {formatDate(source.collected_at)}
                {source.lab_name && <span className="text-muted">, {source.lab_name}</span>}
              </span>
              <span
                aria-hidden="true"
                className="absolute top-0 right-0 size-[0.7rem] bg-line [clip-path:polygon(0_0,100%_100%,0_100%)] group-hover:bg-edta"
              />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Waiting({ subject }: { subject: string }) {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const timer = setTimeout(() => {
      setSlow(true)
    }, SLOW_AFTER_MS)
    return () => {
      clearTimeout(timer)
    }
  }, [])
  return (
    <p className="flex items-start gap-2 text-muted">
      <Icon name="clock" className="mt-1 size-5 motion-safe:animate-pulse" />
      <span>
        Looking through {subject}…
        {slow && (
          <span className="block">
            Still working. When the free AI service is busy, an answer can take up to a minute.
          </span>
        )}
      </span>
    </p>
  )
}

function ExchangeView({
  exchange,
  subject,
  familyId,
  showMember,
  busy,
  onRetry,
  ref,
}: {
  exchange: Exchange
  subject: string
  familyId: string
  showMember: boolean
  /** Another question is being answered: one at a time. */
  busy: boolean
  onRetry: () => void
  ref?: Ref<HTMLElement>
}) {
  return (
    <article ref={ref} className="flex scroll-mt-6 flex-col gap-3">
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-edta-soft px-4 py-2.5 break-words whitespace-pre-line">
          <span className="sr-only">You asked: </span>
          {exchange.question}
        </p>
      </div>
      {exchange.status === 'waiting' && <Waiting subject={subject} />}
      {exchange.status === 'failed' && (
        <div
          role="alert"
          className="flex flex-col items-start gap-3 rounded-lg border border-alert/30 bg-alert-soft px-4 py-3"
        >
          <p className="flex items-start gap-2 font-semibold text-alert">
            <Icon name="alert" className="mt-1 size-5" />
            {exchange.error}
          </p>
          <Button variant="secondary" icon="refresh" disabled={busy} onClick={onRetry}>
            Try again
          </Button>
        </div>
      )}
      {exchange.status === 'answered' && exchange.reply && (
        <div className="flex flex-col gap-4 rounded-lg border border-line border-l-4 border-l-edta bg-surface px-5 py-4">
          <span className="sr-only">Answer:</span>
          <AnswerText text={exchange.reply.reply} />
          <Sources sources={exchange.reply.sources} familyId={familyId} showMember={showMember} />
          <p className="text-sm text-muted">{exchange.reply.disclaimer}</p>
        </div>
      )}
    </article>
  )
}

interface ChatPanelProps {
  kind: ChatKind
  /** The member or family id the questions are about. */
  scopeId: string
  familyId: string
  /** "Amma's results" or "the Rao family's results", for the waiting message. */
  subject: string
  placeholder: string
  suggestions: string[]
}

export function ChatPanel({
  kind,
  scopeId,
  familyId,
  subject,
  placeholder,
  suggestions,
}: ChatPanelProps) {
  const conversation = useConversation(kind, scopeId)
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const lastRef = useRef<HTMLElement>(null)
  const inputId = useId()
  const countId = useId()
  const { exchanges, waiting } = conversation
  const last = exchanges.at(-1)

  // Bring the newest question to the top of the view: its answer then reads from the start,
  // and nothing hides behind the question box, which stays at the bottom of the screen.
  useEffect(() => {
    lastRef.current?.scrollIntoView({ block: 'start' })
  }, [exchanges.length, last?.status])

  function ask(question: string) {
    if (waiting || !question.trim()) return
    setDraft('')
    void conversation.ask(question)
    inputRef.current?.focus()
  }

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    ask(draft)
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter asks; Shift+Enter starts a new line; never while an IME is composing text.
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      ask(draft)
    }
  }

  const nearLimit = draft.length > MAX_MESSAGE_CHARS - 200

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div role="log" aria-live="polite" aria-label="Conversation" className="flex flex-col gap-8">
        {exchanges.length === 0 ? (
          <div className="flex flex-col gap-3">
            <p>Ask in your own words, or start with one of these:</p>
            <ul className="flex flex-col items-start gap-2">
              {suggestions.map((suggestion) => (
                <li key={suggestion}>
                  <Button
                    variant="secondary"
                    className="text-left"
                    onClick={() => {
                      ask(suggestion)
                    }}
                  >
                    {suggestion}
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          exchanges.map((exchange) => (
            <ExchangeView
              key={exchange.id}
              ref={exchange === last ? lastRef : undefined}
              exchange={exchange}
              subject={subject}
              familyId={familyId}
              showMember={kind === 'family'}
              busy={waiting}
              onRetry={() => {
                void conversation.retry(exchange.id)
              }}
            />
          ))
        )}
      </div>

      <form
        onSubmit={onSubmit}
        className="sticky bottom-0 flex flex-col gap-2 border-t border-line bg-paper/95 pt-3 pb-4 backdrop-blur"
      >
        <label htmlFor={inputId} className="font-semibold">
          Your question
        </label>
        <div className="flex items-end gap-3">
          <textarea
            ref={inputRef}
            id={inputId}
            rows={2}
            value={draft}
            maxLength={MAX_MESSAGE_CHARS}
            placeholder={placeholder}
            aria-describedby={nearLimit ? countId : undefined}
            onChange={(event) => {
              setDraft(event.target.value)
            }}
            onKeyDown={onKeyDown}
            className="min-h-12 w-full flex-1 resize-y rounded-lg border border-field bg-surface px-3 py-2 text-base text-ink placeholder:text-muted"
          />
          <Button type="submit" disabled={waiting || !draft.trim()}>
            {waiting ? 'Asking…' : 'Ask'}
          </Button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm text-muted">
          <span className="hidden sm:inline">Enter to ask, Shift+Enter for a new line.</span>
          {nearLimit && (
            <span id={countId}>
              {draft.length.toLocaleString('en-IN')} of {MAX_MESSAGE_CHARS.toLocaleString('en-IN')}{' '}
              characters
            </span>
          )}
          {exchanges.length > 0 && (
            <Button
              variant="quiet"
              icon="undo"
              className="-mr-2 ml-auto"
              disabled={waiting}
              onClick={() => {
                conversation.clear()
                inputRef.current?.focus()
              }}
            >
              Start a new conversation
            </Button>
          )}
        </div>
      </form>
    </div>
  )
}
