"""Chunking text into pages: a long line cut where it breaks least, and never inside a span
the screen must see whole.
"""
import bisect
import re

from . import patterns


CHUNK_TEXT = 1800        # page size for a document with no pages of its own


_CUTS = ("},", "],", ". ", "; ", ", ", " ")   # where an over-long line prefers to break, in order


LINE_CAP = 8192           # characters scanned as one line; a longer one is scanned in pieces


def _flag_spans(line):
    """Where each screen pattern matches in the line, as (start, end) in the line's own
    indices; the text patterns run on the invisible-stripped copy and map back."""
    if len(line) > LINE_CAP:
        # pieces overlap by a pattern's longest reach, so a match straddling a cut is seen whole
        step, spans = LINE_CAP - 600, []
        for at in range(0, len(line), step):
            spans += [(a + at, b + at) for a, b in _flag_spans(line[at:at + LINE_CAP])]
        return _merge(spans)
    keep = [i for i, ch in enumerate(line) if not patterns._STRIP_INVISIBLE.match(ch)]
    visible = "".join(line[i] for i in keep)
    spans = []
    for name, rx in patterns.PATTERNS:
        if name == "hidden characters":
            spans += [m.span() for m in rx.finditer(line)]
        else:
            spans += [(keep[m.start()], keep[m.end() - 1] + 1) for m in rx.finditer(visible) if m.end() > m.start()]
    return _merge(spans)


def _merge(spans):
    merged: list[list[int]] = []    # overlapping matches are one passage: no cut lands between them
    for a, b in sorted(spans):
        if merged and a < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def _cut_at(line, size, spans):
    """Where an over-long line breaks: the latest record, sentence or word break in the
    back half of `size`, never inside a passage the screen matches, because each
    piece is screened alone and "rm" and "-rf ~/" in two pieces both pass. A match has
    no length cap (`curl` padded to any length before `| sh`), so the test is the match
    itself, not a window around the cut. With no clean break, a cut at `size` that would
    split a passage moves to its start, or past its end when the passage starts the line.
    `spans` are _flag_spans for this line, taken once by the caller."""

    def inside(at):             # _split_long strips the head, so a match ending in `\s` needs more
        kept = len(line[:at].rstrip())
        # the first span ending after `kept` is the only one that can hold the cut
        return spans.holding(at, kept)
    lo = size // 2
    for c in _CUTS:
        i = line.rfind(c, lo, size)
        while i >= lo and inside(i + len(c)):
            i = line.rfind(c, lo, i)
        if i >= lo:
            return i + len(c)
    at = size
    if span := inside(at):
        at = span[0]
        if not at:              # the passage starts the line: run long to its end, and on to
            at = span[1]        # the next word's end where the match ends in a space
            if line[at - 1].isspace() and (j := next((j for j in range(at, len(line)) if not line[j].isspace()), None)):
                at = next((k for k in range(j, len(line)) if line[k].isspace()), len(line))
    return min(at, len(line))


class _Spans:
    """`found` (merged, so sorted by start and end alike) and its ends, seen from `base`:
    shifted on read and never copied per cut, which kept a line of thousands of matches
    quadratic."""

    def __init__(self, found, ends, base):
        self.found, self.ends, self.base = found, ends, base

    def holding(self, at, kept):
        """The span a cut at `at` (whose head keeps `kept` characters) would split, or None."""
        k = bisect.bisect_right(self.ends, kept + self.base)
        if k < len(self.found) and self.found[k][0] - self.base < at:
            return (self.found[k][0] - self.base, self.found[k][1] - self.base)
        return None


def _split_long(para, size):
    """An over-long paragraph in pieces of about `size`: whole lines where it has them,
    and a line longer than that (minified JSON, one 60 KB line from the Federal Register
    API) where _cut_at puts the break."""
    pieces, cur = [], ""
    for line in para.split("\n"):
        # scanned once per line and shifted as the line is consumed: a rescan per cut is
        # quadratic, 0.47 s against 0.007 s on a 60 KB line
        found = _flag_spans(line) if len(line) > size else []
        ends = [b for _, b in found]
        base = 0                        # where `line` now starts in the original line
        while len(line) > size:
            at = _cut_at(line, size, _Spans(found, ends, base))
            head, rest = line[:at].rstrip(), line[at:].lstrip()
            base += len(line) - len(rest)
            line = rest
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(head)
        if cur and len(cur) + len(line) + 1 > size:
            pieces.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur.strip():
        pieces.append(cur)
    return pieces


def chunk_text(text, size=CHUNK_TEXT):
    """Paragraph-bounded chunks of about `size` chars, so a chunk never splits a sentence
    the screen would need whole; a paragraph longer than a chunk is split by _split_long."""
    paras = [q for p in re.split(r"\n\s*\n", text) if p.strip()
             for q in (_split_long(p.strip(), size) if len(p.strip()) > size else [p.strip()])]
    pages, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) + 2 > size:
            pages.append(cur)
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        pages.append(cur)
    return pages
