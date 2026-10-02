import { act, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { session } from '../lib/session'
import { DISCLAIMER, fakeApi } from '../test/fakeApi'
import { renderApp } from '../test/render'
import { signIn } from '../test/session'

beforeEach(() => {
  signIn()
})

function setup() {
  const api = fakeApi()
  const family = api.addFamily('Rao family')
  const amma = api.addMember(family.id, {
    display_name: 'Amma',
    sex: 'female',
    date_of_birth: null,
  })
  const report = api.addReport(amma.id, {
    status: 'confirmed',
    collected_at: '2025-03-03T02:35:00Z',
    lab_name: 'Example Labs',
  })
  const memberPath = `/families/${family.id}/members/${amma.id}`
  return { api, family, amma, report, memberPath, askPath: `${memberPath}/ask` }
}

const questionBox = () => screen.getByRole('textbox', { name: 'Your question' })
const conversation = () => screen.getByRole('log', { name: 'Conversation' })

describe('asking about one member', () => {
  it('opens from the member page and says what the AI is told', async () => {
    const { memberPath } = setup()
    const { user } = renderApp(memberPath)
    await user.click(await screen.findByRole('link', { name: 'Ask a question' }))

    expect(
      await screen.findByRole('heading', { level: 1, name: "Ask about Amma's results" }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/The AI never sees Amma's name: it is told "the patient"/),
    ).toBeVisible()
    expect(screen.getByRole('link', { name: 'Amma' })).toBeInTheDocument()
  })

  it('answers a suggested question, with the reports used and the disclaimer', async () => {
    const { api, family, amma, report, askPath } = setup()
    api.answerChat(
      'Two results were outside the range on **3 Mar 2025**:\n- Ferritin low\n- LDL high',
    )
    const release = api.holdChat()
    const { user } = renderApp(askPath)

    await user.click(
      await screen.findByRole('button', {
        name: 'What is outside the range in the latest report?',
      }),
    )
    expect(await screen.findByText("Looking through Amma's results…")).toBeVisible()
    expect(screen.getByRole('button', { name: 'Asking…' })).toBeDisabled()
    expect(api.chatRequests()).toEqual([
      [{ role: 'user', content: 'What is outside the range in the latest report?' }],
    ])
    expect(api.calls.at(-1)?.path).toBe(`/patients/${amma.id}/chat`)

    release()
    const log = conversation()
    expect(await within(log).findByText('3 Mar 2025', { selector: 'strong' })).toHaveProperty(
      'tagName',
      'STRONG',
    )
    expect(
      within(log)
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual(expect.arrayContaining(['Ferritin low', 'LDL high']))
    const source = within(log).getByRole('link', { name: '3 Mar 2025, Example Labs' })
    expect(source).toHaveAttribute(
      'href',
      `/families/${family.id}/members/${amma.id}/reports/${report.id}`,
    )
    expect(within(log).getByText(DISCLAIMER)).toBeVisible()
    expect(screen.queryByText("Looking through Amma's results…")).not.toBeInTheDocument()
  })

  it('explains a long wait', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const { api, askPath } = setup()
    const release = api.holdChat()
    const { user } = renderApp(askPath)
    await user.type(
      await screen.findByRole('textbox', { name: 'Your question' }),
      'Ferritin?{Enter}',
    )
    await screen.findByText("Looking through Amma's results…")
    expect(screen.queryByText(/Still working/)).not.toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(8_000)
    })
    expect(
      screen.getByText(
        'Still working. When the free AI service is busy, an answer can take up to a minute.',
      ),
    ).toBeVisible()
    release()
    expect(await screen.findByText('You asked: Ferritin?')).toBeVisible()
    expect(screen.queryByText(/Still working/)).not.toBeInTheDocument()
  })

  it('sends the earlier questions and answers with a follow-up', async () => {
    const { api, askPath } = setup()
    api.answerChat('Ferritin was 4.10 ng/mL.', 'It went up from 4.10 to 20.5.')
    const { user } = renderApp(askPath)

    await user.type(await screen.findByRole('textbox', { name: 'Your question' }), 'Ferritin?')
    await user.keyboard('{Enter}')
    await screen.findByText('Ferritin was 4.10 ng/mL.')
    await user.type(questionBox(), 'Has it changed?{Enter}')
    await screen.findByText('It went up from 4.10 to 20.5.')

    expect(api.chatRequests()[1]).toEqual([
      { role: 'user', content: 'Ferritin?' },
      { role: 'assistant', content: 'Ferritin was 4.10 ng/mL.' },
      { role: 'user', content: 'Has it changed?' },
    ])
  })

  it('starts a new line with Shift+Enter, and does not send an empty question', async () => {
    const { api, askPath } = setup()
    const { user } = renderApp(askPath)
    const box = await screen.findByRole('textbox', { name: 'Your question' })

    await user.type(box, '{Enter}   {Enter}')
    expect(api.chatRequests()).toEqual([])
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()

    await user.clear(box)
    await user.type(box, 'First line{Shift>}{Enter}{/Shift}second line')
    expect(box).toHaveValue('First line\nsecond line')
    await user.click(screen.getByRole('button', { name: 'Ask' }))
    await screen.findByText(/You asked: First line/)
    expect(api.chatRequests()[0]?.at(-1)?.content).toBe('First line\nsecond line')
    expect(box).toHaveValue('')
  })

  it('counts characters near the limit', async () => {
    const { askPath } = setup()
    const { user } = renderApp(askPath)
    const box = await screen.findByRole('textbox', { name: 'Your question' })

    await user.click(box)
    await user.paste('a'.repeat(1700))
    expect(screen.queryByText(/of 2,000 characters/)).not.toBeInTheDocument()
    await user.paste('a'.repeat(150))
    expect(screen.getByText('1,850 of 2,000 characters')).toBeVisible()
    expect(box).toHaveAccessibleDescription('1,850 of 2,000 characters')
  })

  it('shows why a question failed, and asks it again', async () => {
    const { api, askPath } = setup()
    let busy = true
    api.override((call) =>
      busy && call.path.endsWith('/chat')
        ? { status: 503, body: { detail: 'The assistant is busy. Please try again in a minute.' } }
        : undefined,
    )
    const { user } = renderApp(askPath)
    await user.type(
      await screen.findByRole('textbox', { name: 'Your question' }),
      'Ferritin?{Enter}',
    )

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The assistant is busy. Please try again in a minute.')
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled() // box is empty again

    // One question at a time: no retry while another is being answered.
    const release = api.holdChat()
    await user.type(questionBox(), 'Another?{Enter}')
    expect(within(alert).getByRole('button', { name: 'Try again' })).toBeDisabled()
    busy = false
    release()
    await screen.findByText('You asked: Another?')

    await user.click(within(alert).getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('You asked: Ferritin?')).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(api.chatRequests()).toHaveLength(3)
    // Asked again with only what came before it, not the later question.
    expect(api.chatRequests()[2]).toEqual([{ role: 'user', content: 'Ferritin?' }])
  })

  it('keeps the conversation while moving around, until a new one is started', async () => {
    const { memberPath, askPath } = setup()
    const { user, router } = renderApp(askPath)
    await user.type(
      await screen.findByRole('textbox', { name: 'Your question' }),
      'Ferritin?{Enter}',
    )
    await screen.findByText('You asked: Ferritin?')

    await act(() => router.navigate(memberPath))
    await screen.findByRole('heading', { level: 1, name: 'Amma' })
    await act(() => router.navigate(askPath))
    expect(await screen.findByText('You asked: Ferritin?')).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Start a new conversation' }))
    expect(screen.queryByText('You asked: Ferritin?')).not.toBeInTheDocument()
    expect(screen.getByText('Ask in your own words, or start with one of these:')).toBeVisible()
    expect(questionBox()).toHaveFocus()
  })

  it('forgets the conversation when the user logs out', async () => {
    const { askPath } = setup()
    const { user, router } = renderApp(askPath)
    await user.type(
      await screen.findByRole('textbox', { name: 'Your question' }),
      'Ferritin?{Enter}',
    )
    await screen.findByText('You asked: Ferritin?')

    await user.click(screen.getByRole('button', { name: 'Log out' }))
    await screen.findByRole('heading', { name: 'Sign in' })
    act(() => {
      signIn()
    })
    await act(() => router.navigate(askPath))
    expect(
      await screen.findByText('Ask in your own words, or start with one of these:'),
    ).toBeVisible()
    expect(screen.queryByText('You asked: Ferritin?')).not.toBeInTheDocument()
  })

  it('drops an answer that arrives after the user logged out', async () => {
    const { api, askPath } = setup()
    const release = api.holdChat()
    const { user, router, queryClient } = renderApp(askPath)
    await user.type(
      await screen.findByRole('textbox', { name: 'Your question' }),
      'Ferritin?{Enter}',
    )
    await screen.findByText("Looking through Amma's results…")

    act(() => {
      session.clear()
    })
    const answered = api.answered()
    release()
    await act(() => answered)
    act(() => {
      signIn()
    })
    await act(() => router.navigate(askPath))
    await screen.findByText('Ask in your own words, or start with one of these:')
    expect(queryClient.getQueriesData({ queryKey: ['chat'] }).flatMap(([, data]) => data)).toEqual(
      [],
    )
  })

  it('is not found under another family’s address', async () => {
    const { api, amma } = setup()
    const other = api.addFamily('Other family')
    renderApp(`/families/${other.id}/members/${amma.id}/ask`)
    expect(
      await screen.findByRole('heading', { name: "This family member can't be found" }),
    ).toBeInTheDocument()
    expect(api.chatRequests()).toEqual([])
  })
})

describe('asking about the whole family', () => {
  it('is offered only once the family has members', async () => {
    const { api, family } = setup()
    const empty = api.addFamily('New family')
    const { router } = renderApp(`/families/${empty.id}`)
    await screen.findByRole('heading', { level: 1, name: 'New family' })
    expect(screen.queryByRole('link', { name: 'Ask about the family' })).not.toBeInTheDocument()

    await act(() => router.navigate(`/families/${family.id}`))
    expect(await screen.findByRole('link', { name: 'Ask about the family' })).toHaveAttribute(
      'href',
      `/families/${family.id}/ask`,
    )
  })

  it('names the member of each report it used', async () => {
    const { api, family } = setup()
    const appa = api.addMember(family.id, {
      display_name: 'Appa',
      sex: 'male',
      date_of_birth: null,
    })
    api.addReport(appa.id, {
      status: 'confirmed',
      collected_at: '2025-06-10T03:00:00Z',
      lab_name: 'Example Labs',
    })
    api.answerChat('Member results compared.')
    const { user } = renderApp(`/families/${family.id}/ask`)

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Ask about Rao family' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/it is told "Member A", "Member B" and so on/)).toBeVisible()
    await user.click(
      screen.getByRole('button', { name: 'Who has results outside the range right now?' }),
    )
    await screen.findByText('Member results compared.')
    expect(api.calls.at(-1)?.path).toBe(`/families/${family.id}/chat`)
    const log = conversation()
    expect(within(log).getByRole('link', { name: 'Amma, 3 Mar 2025, Example Labs' })).toBeVisible()
    expect(within(log).getByRole('link', { name: 'Appa, 10 Jun 2025, Example Labs' })).toBeVisible()
  })

  it('asks for a member first when the family has none', async () => {
    const { api } = setup()
    const empty = api.addFamily('New family')
    renderApp(`/families/${empty.id}/ask`)
    expect(
      await screen.findByText('Add a family member first, then ask about their results.'),
    ).toBeVisible()
    expect(screen.queryByRole('textbox', { name: 'Your question' })).not.toBeInTheDocument()
  })

  it('is not found for a family that is not yours', async () => {
    setup()
    renderApp('/families/family-unknown/ask')
    expect(
      await screen.findByRole('heading', { name: "This family can't be found" }),
    ).toBeInTheDocument()
  })
})
