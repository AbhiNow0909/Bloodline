"""Split a report's scrubbed text into chunks for embedding.

Each results page is chunked on its own (a chunk never mixes two sample types), along line
breaks, so a test's name, value, printed range and method usually stay together. Chunks are
prefixed with the page's sample type, like the text the structuring model reads, and
consecutive chunks of a page share their boundary line(s) so nothing is cut off from its
context. The input is the scrubbed text stored at extraction; nothing here adds identity.
"""

from collections.abc import Sequence

from app.services.extraction import ResultsPage

# bge-small reads at most 512 tokens; ~900 characters of lab text is well under that.
MAX_CHUNK_CHARS = 900
OVERLAP_LINES = 1


def _split_long_line(line: str, limit: int) -> list[str]:
    """A single line longer than the limit, cut at spaces (or hard, if there are none)."""
    pieces: list[str] = []
    rest = line
    while len(rest) > limit:
        cut = rest.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        pieces.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        pieces.append(rest)
    return pieces


def chunk_page(
    text: str,
    header: str,
    *,
    max_chars: int = MAX_CHUNK_CHARS,
    overlap_lines: int = OVERLAP_LINES,
) -> list[str]:
    """Chunks of one page's text, each starting with `header` (e.g. "Sample type: SERUM")."""
    budget = max_chars - len(header) - 1
    lines: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())  # collapse runs of spaces from the PDF layout
        if line:
            lines.extend(_split_long_line(line, budget))
    if not lines:
        return []

    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) + 1 > budget:
            chunks.append("\n".join([header, *current]))
            # Carry the last line(s) over, unless that alone would overflow the next chunk.
            carried = current[-overlap_lines:] if overlap_lines else []
            if sum(len(c) + 1 for c in carried) + len(line) + 1 > budget:
                carried = []
            current = list(carried)
            size = sum(len(c) + 1 for c in current)
        current.append(line)
        size += len(line) + 1
    chunks.append("\n".join([header, *current]))
    return chunks


def chunk_report(pages: Sequence[ResultsPage], *, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Every page's chunks, in page order."""
    chunks: list[str] = []
    for page in pages:
        header = f"Sample type: {page.sample_type or 'unknown'}"
        chunks.extend(chunk_page(page.text, header, max_chars=max_chars))
    return chunks
