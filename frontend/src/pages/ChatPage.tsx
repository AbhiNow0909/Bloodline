import { useParams } from 'react-router'

import { PageHeader } from '../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { ChatPanel } from '../chat/ChatPanel'
import { ApiError } from '../lib/api'
import { useFamily, useMember, useMembers } from '../lib/queries'
import { NotFound } from './NotFoundPage'

const MEMBER_SUGGESTIONS = [
  'What is outside the range in the latest report?',
  'What changed since the previous report?',
  'Explain the latest report in simple words.',
]

const FAMILY_SUGGESTIONS = [
  'Who has results outside the range right now?',
  "When was each person's last report?",
  'Whose results changed most since their last report?',
]

/** Ask about one family member's results. */
export function MemberChatPage() {
  const { familyId = '', memberId = '' } = useParams()
  const family = useFamily(familyId)
  const member = useMember(memberId)

  const error = family.error ?? member.error
  const misplaced = member.data !== undefined && member.data.family_id !== familyId
  if ((error instanceof ApiError && error.status === 404) || misplaced) {
    return <NotFound what="family member" />
  }
  if (error) return <ErrorState error={error} />
  if (!family.data || !member.data) return <LoadingState />

  const name = member.data.display_name
  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        crumbs={[
          { label: 'Families', to: '/families' },
          { label: family.data.name, to: `/families/${familyId}` },
          { label: name, to: `/families/${familyId}/members/${memberId}` },
          { label: 'Ask' },
        ]}
        title={`Ask about ${name}'s results`}
        subtitle={`Answers come only from ${name}'s saved reports. The AI never sees ${name}'s name: it is told "the patient".`}
      />
      <ChatPanel
        kind="member"
        scopeId={memberId}
        familyId={familyId}
        subject={`${name}'s results`}
        placeholder={`For example: has ${name}'s haemoglobin changed?`}
        suggestions={MEMBER_SUGGESTIONS}
      />
    </div>
  )
}

/** Ask across every member of one family. */
export function FamilyChatPage() {
  const { familyId = '' } = useParams()
  const family = useFamily(familyId)
  const members = useMembers(familyId)

  const error = family.error ?? members.error
  if (error instanceof ApiError && error.status === 404) return <NotFound what="family" />
  if (error) return <ErrorState error={error} />
  if (!family.data || !members.data) return <LoadingState />

  const name = family.data.name
  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        crumbs={[
          { label: 'Families', to: '/families' },
          { label: name, to: `/families/${familyId}` },
          { label: 'Ask' },
        ]}
        title={`Ask about ${name}`}
        subtitle={`Answers come from the saved reports of everyone in ${name}. The AI never sees names: it is told "Member A", "Member B" and so on.`}
      />
      {members.data.length === 0 ? (
        <EmptyState>Add a family member first, then ask about their results.</EmptyState>
      ) : (
        <ChatPanel
          kind="family"
          scopeId={familyId}
          familyId={familyId}
          subject={`the results of everyone in ${name}`}
          placeholder="For example: who has high LDL?"
          suggestions={FAMILY_SUGGESTIONS}
        />
      )}
    </div>
  )
}
