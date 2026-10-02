import { describe, expect, it } from 'vitest'

import { HISTORY_EXCHANGES, MAX_MESSAGE_CHARS, messagesFor, type Exchange } from './conversation'

const answered = (n: number): Exchange => ({
  id: `q${String(n)}`,
  question: `Question ${String(n)}`,
  status: 'answered',
  reply: { reply: `Answer ${String(n)}`, sources: [], disclaimer: '' },
})

describe('messagesFor', () => {
  it('sends only the question when nothing came before', () => {
    expect(messagesFor([], 'How is ferritin?')).toEqual([
      { role: 'user', content: 'How is ferritin?' },
    ])
  })

  it('sends the last few answered exchanges before the question, oldest first', () => {
    const earlier = [1, 2, 3, 4, 5, 6].map(answered)
    const messages = messagesFor(earlier, 'And now?')
    expect(messages).toHaveLength(HISTORY_EXCHANGES * 2 + 1)
    expect(messages.slice(0, 2)).toEqual([
      { role: 'user', content: 'Question 3' },
      { role: 'assistant', content: 'Answer 3' },
    ])
    expect(messages.at(-1)).toEqual({ role: 'user', content: 'And now?' })
  })

  it('leaves out questions that failed or are still waiting', () => {
    const earlier: Exchange[] = [
      answered(1),
      { id: 'q2', question: 'Failed one', status: 'failed', error: 'Busy' },
      { id: 'q3', question: 'Waiting one', status: 'waiting' },
    ]
    expect(messagesFor(earlier, 'Next').map((m) => m.content)).toEqual([
      'Question 1',
      'Answer 1',
      'Next',
    ])
  })

  it('keeps every message within the server’s length limit', () => {
    const long = { ...answered(1), reply: { reply: 'a'.repeat(5000), sources: [], disclaimer: '' } }
    const messages = messagesFor([long], 'b'.repeat(5000))
    expect(messages.every((m) => m.content.length <= MAX_MESSAGE_CHARS)).toBe(true)
  })
})
