"""The sieve as data: `sift` reads a document, ranks its pages against the questions,
screens and scores the ones returned, and gives back a `SiftResult`; `render` prints one;
`decipher` hands the screened pages to the relay and keeps only lines found verbatim in them.

Nothing downstream reads the printed text: decipher takes its notes from the result, so a
page that prints `withheld whole` or `relay failed (` is only a page.
"""
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

from . import htmltext
from .chunk import CHUNK_TEXT  # noqa: F401  (kept beside the other sizes a reader looks for)
from .documents import acquire, render_pages
from .pdf import printed_numbers
from .question import _tags, split_prompt, topic_parts
from .rank import MIN_SCORE_NOTE, PAGES_DEFAULT, interleave, rank_each
from .relay import relay, verbatim
from .score import score_pages
from .screen import hold, screen

RELAY_FAILED = 5        # decipher's exit code when no relay answered: screened, never deciphered


class Page(NamedTuple):
    n: int                       # 1-based, physical
    score: float                 # the ranking's
    body: str                    # screened, or the placeholder of a page withheld whole
    asks: list                   # which questions ranked it
    scored: Optional[float]      # the scorer's instructs-agent, None when not scored


class SiftResult(NamedTuple):
    name: str
    questions: List[str]
    unit: str                    # "page" for a PDF, "chunk" otherwise
    total: int                   # pages in the document
    method: str                  # how it was ranked
    notes: List[str]             # header lines after the counts, in order
    pages: List[Page]
    labels: dict                 # physical page -> printed label
    scoring: bool                # the scorer ran, so an unscored page says so
    score_note: Optional[str]
    rendered: List[str]          # --render's PNG paths
    render_error: Optional[str]
    whole: List[Tuple[int, str]]  # (page, id) withheld whole although ranked as answering
    withheld: int
    store: Path


def sift(file: str, questions: List[str], store: Path, *, pages: int = PAGES_DEFAULT, split: bool = False,
         score: bool = False, render: bool = False, strict: bool = False, deadline=None) -> SiftResult:
    """`strict` (fetch --decipher): a page the scorer could not score is withheld, as one it
    flagged is, since a second model reads whatever passes."""
    doc, kind, empty = acquire(file)
    notes: List[str] = []
    if split:
        asked = len(questions)
        questions = [x for q in questions for x in (split_prompt(q) or [q])]
        if pages == PAGES_DEFAULT:              # every part gets a page of its own, unless --pages said otherwise
            pages = max(pages, len(questions))
        if len(questions) > asked:
            notes.append(f"--split asked {len(questions)} questions in place of {asked}")
    parts = [topic_parts(q) for q in questions]
    all_orders, method = rank_each(questions + [x for ps in parts for x in ps], doc, deadline)
    orders, part_orders = all_orders[:len(questions)], iter(all_orders[len(questions):])
    top = interleave(orders, pages)
    unit = "page" if kind == "pdf" else "chunk"
    many = len(questions) > 1
    returned = {i for i, _, _ in top}
    for k, ps in enumerate(parts, 1):
        lost = [(x, o[0][0] + 1) for x in ps if (o := next(part_orders)) and o[0][0] not in returned]
        if lost:
            notes.append(f"{'question ' + str(k) if many else 'the question'} strings {len(ps)} parts into one "
                         f"ranking, which left out "
                         + "; ".join(f"{unit} {n}, the best for \"{x}\"" for x, n in lost)
                         + ": if those are separate questions, ask each on its own (one --ask each)")
    labels = printed_numbers(file, doc) if kind == "pdf" else {}
    if labels:
        notes.append("this PDF prints its own page numbers: each heading gives the printed one, "
                     "and #page=N takes the physical one")
    if empty:
        notes.append(f"no text layer on {unit}s {', '.join(map(str, empty))}"
                     + (" (rendered below)" if render else " (pass --render to get them as PNGs)"))
    for k, order in enumerate(orders, 1):
        if order and order[0][1] < MIN_SCORE_NOTE:
            notes.append(f"best score {order[0][1]:.2f} is weak: the document may not answer "
                         + (f"question {k}" if many else "this question"))
    # Screen first, then score: the scorer may be a networked model, and what it sees is
    # only what the agent would see.
    screened, withheld = [], 0
    for i, s, qs in sorted(top, key=lambda t: t[0]):
        body, held = screen(doc[i].rstrip(), file, i + 1, store)
        withheld += len(held)
        screened.append(Page(i + 1, s, body, qs, None))
    whole: List[Tuple[int, str]] = []
    score_note = None
    if score:
        scores, threshold, score_note = score_pages([(p.n, p.body) for p in screened], deadline)
        for k, p in enumerate(screened):
            v = scores.get(p.n)
            unread = strict and threshold is not None and v is None
            if threshold is not None and ((v is not None and v >= threshold) or unread):
                why = "the scorer did not answer" if unread else f"scorer instructs-agent {v:.2f}"
                line, held_whole = hold(p.body, [why], file, p.n, store)
                screened[k] = p._replace(body=line, scored=v)
                withheld += 1
                whole.append((p.n, held_whole["id"]))
            else:
                screened[k] = p._replace(scored=v)
    rendered, render_error = ([], None)
    if render and empty:
        rendered, render_error = render_pages(file, empty, store)
    return SiftResult(Path(file).name, questions, unit, len(doc), method, notes, screened, labels, score,
                      score_note, rendered, render_error, whole, withheld, store)


def head(r: SiftResult) -> str:
    many = len(r.questions) > 1
    lines = [f"# grille sift: {r.name}\n"]
    lines += [f"question {k}: {q}  " if many else f"question: {q}  " for k, q in enumerate(r.questions, 1)]
    lines.append(f"{r.total} {r.unit}s, {len(r.pages)} returned, ranked by {r.method}"
                 + (", the questions taking turns" if many else ""))
    lines += r.notes
    if r.score_note:
        lines.append(f"score: {r.score_note}")
    return "\n".join(lines)


def body(r: SiftResult) -> str:
    """The returned pages, each under its heading: what the relay reads and verbatim checks against."""
    many = len(r.questions) > 1
    out = []
    for p in r.pages:
        extra = (f", instructs-agent {p.scored:.2f}" if p.scored is not None
                 else ", unscored" if r.scoring else "")
        which = f", {_tags(p.asks)}" if many else ""
        printed = f"printed {r.labels[p.n]}, " if p.n in r.labels else ""
        out.append(f"\n## {r.unit} {p.n} ({printed}score {p.score:.2f}{which}{extra})\n\n{p.body}")
    return "\n".join(out)


def tail(r: SiftResult) -> str:
    out = []
    if r.rendered or r.render_error:
        out.append("\nrendered:\n" + "\n".join(r.rendered) + (f"\n{r.render_error}" if r.render_error else ""))
    # A whole page ranked as answering the question may hold the figure; closing it
    # silently turns "withheld" into "no source found", which the source floor forbids.
    for n, wid in r.whole:
        out.append(f"\n{r.unit} {n} was ranked as answering the question and withheld whole: "
                   f"read it as data with `grille show {wid}` before declaring the field unsourced")
    return "\n".join(out)


def render(r: SiftResult) -> str:
    return htmltext.printable("\n".join(x for x in (head(r), body(r), tail(r)) if x))


def footer(r: SiftResult) -> str:
    return f"\n---\n{r.withheld} span{'s' if r.withheld != 1 else ''} withheld; store {r.store}"


def decipher(r: SiftResult, cfg: dict, file: str, deadline=None) -> Tuple[str, int]:
    """-> (text, exit code). The relay reads the header and the screened pages; only its
    lines found verbatim in the pages are kept, and the rest are held behind an id."""
    pages = body(r)
    answer, who = relay(r.questions, head(r) + "\n" + pages, cfg, deadline)
    if answer is None:
        return f"relay failed ({who}); the screened pages follow whole\n\n{render(r)}", RELAY_FAILED
    out = [head(r).rstrip()]
    if answer.strip() == "NOT FOUND":
        out.append(f"\n{who}: NOT FOUND in the screened pages; `grille sift {file} --ask ...` shows them")
        return "\n".join(out), 0
    kept, dropped = verbatim(answer, pages)
    out.append(f"relayed by {who}; {len(kept)} line{'s' if len(kept) != 1 else ''} verified verbatim "
               f"against the screened pages\n")
    out.append("\n".join(kept) if kept else "nothing verbatim came back")
    if dropped:
        line, _ = hold("\n".join(dropped), ["relay line not verbatim in the screened pages"], file, 0, r.store)
        out.append(line)
    t = tail(r)
    if t:
        out.append(t)
    return "\n".join(out), 0


def emit(text: str, r: SiftResult) -> None:
    print(htmltext.printable(text))
    print(footer(r), file=sys.stderr)
