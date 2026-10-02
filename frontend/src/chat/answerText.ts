/**
 * The assistant's answers are plain text, but the model sometimes uses a little Markdown even
 * when asked not to: "- " lists, "1. " lists, **bold**, a "### heading". This turns that into
 * paragraphs, lists and bold spans that React renders as text, so nothing in an answer is ever
 * treated as HTML.
 */

export interface Span {
  text: string
  bold: boolean
}

export type Block =
  | { kind: 'paragraph'; lines: Span[][] }
  | { kind: 'bullets'; items: Span[][] }
  | { kind: 'numbers'; items: Span[][] }

const BULLET = /^\s*(?:[-*•–]\s+)(.*)$/
const NUMBERED = /^\s*\d{1,2}[.)]\s+(.*)$/
const HEADING = /^\s*#{1,6}\s+(.*)$/

/** "**bold** text" → spans. Unpaired asterisks are left as they are. */
export function spans(line: string): Span[] {
  const result: Span[] = []
  const pattern = /\*\*(.+?)\*\*|__(.+?)__/g
  let last = 0
  for (const match of line.matchAll(pattern)) {
    if (match.index > last) result.push({ text: line.slice(last, match.index), bold: false })
    result.push({ text: match[1] ?? match[2] ?? '', bold: true })
    last = match.index + match[0].length
  }
  if (last < line.length) result.push({ text: line.slice(last), bold: false })
  return result.filter((span) => span.text !== '')
}

export function parseAnswer(text: string): Block[] {
  const blocks: Block[] = []
  // A blank line ends the current block; the next line starts a new one.
  let open = false

  for (const raw of text.replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trimEnd()
    if (!line.trim()) {
      open = false
      continue
    }
    const last = open ? blocks.at(-1) : undefined
    open = true
    const bullet = BULLET.exec(line)
    const numbered = bullet ? null : NUMBERED.exec(line)
    if (bullet || numbered) {
      const kind = bullet ? 'bullets' : 'numbers'
      const item = spans((bullet ?? numbered)?.[1] ?? '')
      if (last && last.kind !== 'paragraph' && last.kind === kind) last.items.push(item)
      else blocks.push({ kind, items: [item] })
      continue
    }
    const heading = HEADING.exec(line)
    const content = heading ? [{ text: heading[1] ?? '', bold: true }] : spans(line.trim())
    if (last?.kind === 'paragraph') last.lines.push(content)
    else blocks.push({ kind: 'paragraph', lines: [content] })
  }
  return blocks
}
