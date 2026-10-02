import { describe, expect, it } from 'vitest'

import { parseAnswer, spans } from './answerText'

describe('spans', () => {
  it('reads **bold** and __bold__, and leaves stray asterisks alone', () => {
    expect(spans('Ferritin was **4.10 ng/mL** on __3 Mar 2024__.')).toEqual([
      { text: 'Ferritin was ', bold: false },
      { text: '4.10 ng/mL', bold: true },
      { text: ' on ', bold: false },
      { text: '3 Mar 2024', bold: true },
      { text: '.', bold: false },
    ])
    expect(spans('5 * 3 is not bold**')).toEqual([{ text: '5 * 3 is not bold**', bold: false }])
  })
})

describe('parseAnswer', () => {
  it('splits paragraphs on blank lines and keeps line breaks within one', () => {
    expect(parseAnswer('First line\nsecond line\n\nNext paragraph')).toEqual([
      {
        kind: 'paragraph',
        lines: [[{ text: 'First line', bold: false }], [{ text: 'second line', bold: false }]],
      },
      { kind: 'paragraph', lines: [[{ text: 'Next paragraph', bold: false }]] },
    ])
  })

  it('turns "-", "*", "•" lines into a bulleted list and "1." lines into a numbered one', () => {
    const blocks = parseAnswer(
      'Outside the range:\n- Ferritin **low**\n* LDL high\n• HbA1c high\n\n1. First\n2) Second',
    )
    expect(blocks.map((b) => b.kind)).toEqual(['paragraph', 'bullets', 'numbers'])
    expect(blocks[1]).toEqual({
      kind: 'bullets',
      items: [
        [
          { text: 'Ferritin ', bold: false },
          { text: 'low', bold: true },
        ],
        [{ text: 'LDL high', bold: false }],
        [{ text: 'HbA1c high', bold: false }],
      ],
    })
    expect(blocks[2]).toEqual({
      kind: 'numbers',
      items: [[{ text: 'First', bold: false }], [{ text: 'Second', bold: false }]],
    })
  })

  it('shows a Markdown heading as a bold line', () => {
    expect(parseAnswer('### Summary\nAll in range.')).toEqual([
      {
        kind: 'paragraph',
        lines: [[{ text: 'Summary', bold: true }], [{ text: 'All in range.', bold: false }]],
      },
    ])
  })

  it('keeps HTML as plain text and ignores empty input', () => {
    expect(parseAnswer('<img src=x onerror=alert(1)>')).toEqual([
      { kind: 'paragraph', lines: [[{ text: '<img src=x onerror=alert(1)>', bold: false }]] },
    ])
    expect(parseAnswer('  \n\n ')).toEqual([])
  })

  it('does not take a range or a negative number for a list', () => {
    expect(parseAnswer('-3 is not a bullet\n12.5 - 15.0 g/dL').map((b) => b.kind)).toEqual([
      'paragraph',
    ])
  })
})
