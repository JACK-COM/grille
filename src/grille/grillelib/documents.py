"""Reading a document into pages: pdftotext for a PDF, HTML to text, plain text chunked; a
page with no text layer rendered by pdftoppm.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional, Tuple

import _guard as guard

from . import chunk
from . import htmltext
from . import patterns
from . import pdf


# A line the page starts with `[grille` would pass for Grille's own placeholder: the scorer
# strips those before scoring, and a reader takes them for Grille's word.
_FRAMING = re.compile(r"(?i)()\[(?=[\s\u200b-\u200f\u2060-\u2064\ufeff]*grille\b)")
def _unpose(page):
    """The page with every line that could pass for Grille's own marked as the page's: a
    bracketed `grille` read through the screen's skeleton (so `[gr\u0456lle` and a soft
    hyphen count), and a heading, header or status line Grille prints, after controls are
    made spaces (`\x01## chunk 7` printed as ` ## chunk 7`)."""
    page = htmltext.printable(page)
    out, at = [], 0
    for m in re.finditer("[\\[\uff3b]", page):
        if patterns.skeleton(page[m.end():m.end() + 16]).lower().lstrip(" \u00ad\ufe0f\ufe0e").startswith("grille"):
            out.append(page[at:m.start()] + "[the page writes: ")
            at = m.end()
    page = "".join(out) + page[at:]
    lines = []
    for line in page.split("\n"):
        lead = len(line) - len(line.lstrip(_LEAD_CHARS))
        if _POSE.match(patterns.skeleton(line[lead:])):
            line = line[:lead] + "(the page writes) " + line[lead:]
        lines.append(line)
    return "\n".join(lines)


_LEAD_CHARS = " \t\u200b\u200c\u200d\u200e\u200f\u2060\u2061\u2062\u2063\u2064\ufeff\u00ad\u180e"
_POSE = re.compile(r"(?i)(?=#{1,2}\s|---\s*$|(?:page|chunk)\s+\d+\s+was ranked|question(?:\s+\d+)?:|score:|relayed by\b|relay failed\b)")
EMPTY_PAGE = 20          # fewer stripped chars than this and the page has no text layer

TOOL_TIMEOUT = 60       # seconds pdftotext or pdftoppm may run on one file or page


class Format(NamedTuple):
    """A document format, declared once: a new one is one entry in FORMATS."""
    kind: str
    suffixes: Tuple[str, ...]                     # read from a file by these
    ctypes: Tuple[str, ...]                       # a fetched body of these content types
    read: Callable[[Path], Tuple[List[str], List[int]]]   # -> (pages, pages with no text layer)
    unit: str = "chunk"                           # what one of its pages is called
    sniff: Callable[[bytes], bool] = lambda head: False   # a body the server did not type
    labels: Callable[[str, List[str]], dict] = lambda path, pages: {}   # page -> printed number
    binary: bool = False                          # saved as fetched, not decoded
    ext: str = "txt"
    note: Callable[[bytes, str], Optional[str]] = lambda data, text: None   # fetch's warning on the body


def _read_pdf(p):
    if not shutil.which("pdftotext"):
        sys.exit("grille: pdftotext not found; brew install poppler")
    try:
        # a hostile PDF can hold pdftotext for as long as it likes: bounded, and UTF-8 whatever the locale
        r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(p), "-"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=TOOL_TIMEOUT)
    except subprocess.TimeoutExpired:
        sys.exit(f"grille: pdftotext ran past {TOOL_TIMEOUT}s on {p}")
    if r.returncode:
        how = (f"killed by signal {-r.returncode}" if r.returncode < 0
               else f"exit {r.returncode}")
        sys.exit(f"grille: pdftotext failed on {p} ({how}): "
                 f"{guard.relay(r.stderr.strip(), 200) or 'no stderr; a sandbox killing it looks like this'}")
    # -layout pads columns with spaces to the page width; 40% of the bytes on a
    # typical manual page. Three spaces keep a table readable, the rest are cut.
    pages = [re.sub(r"[ \t]{4,}", "   ", pg).replace(" \n", "\n") for pg in r.stdout.split("\f")]
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages, [i + 1 for i, t in enumerate(pages) if len(t.strip()) < EMPTY_PAGE]


def _read_html(p):
    t = htmltext._Text()
    t.feed(p.read_text(encoding="utf-8", errors="replace"))
    return chunk._chunk_text(re.sub(r"\n{3,}", "\n\n", t.text())), []


def _app_shell(data, text):
    t = htmltext._Text()
    t.feed(text)
    if len(t.text(chrome=True).strip()) < htmltext.APP_SHELL and b"<script" in data.lower():
        return ("this page carries scripts and almost no text: a JavaScript app renders "
                "nothing here, so read it in the browser")
    return None


def _read_text(p):
    return chunk._chunk_text(p.read_text(encoding="utf-8", errors="replace")), []


PDF = Format("pdf", (".pdf",), ("application/pdf",), _read_pdf, unit="page",
             sniff=lambda head: head[:5] == b"%PDF-", labels=lambda path, pages: pdf.printed_numbers(path, pages),
             binary=True, ext="pdf")
HTML = Format("html", (".html", ".htm"), ("text/html", "application/xhtml+xml"), _read_html,
              sniff=lambda head: b"<html" in head.lower() or b"<!doctype html" in head.lower(), ext="html",
              note=_app_shell)
TEXT = Format("text", (), (), _read_text)
FORMATS = (PDF, HTML, TEXT)           # TEXT last: whatever no other format claims


def by_kind(kind):
    return next((f for f in FORMATS if f.kind == kind), TEXT)


def of_file(path):
    return next((f for f in FORMATS if Path(path).suffix.lower() in f.suffixes), TEXT)


def of_fetched(data, ctype):
    """An explicit content type is trusted; the body is sniffed only where the server said
    nothing useful, so a text/plain excerpt that shows HTML markup stays text. A PDF's magic
    wins over any type."""
    if PDF.sniff(data[:8]):
        return PDF
    typed = next((f for f in FORMATS if ctype in f.ctypes), None)
    if typed:
        return typed
    if ctype in ("", "application/octet-stream"):
        return next((f for f in FORMATS if f.sniff(data[:2048])), TEXT)
    return TEXT


def acquire(path):
    """-> (pages: [str], kind, empty: [page numbers with no text layer]). Page numbers are 1-based."""
    p = Path(path)
    if not p.exists():
        sys.exit(f"grille: no such file: {p}")
    fmt = of_file(p)
    pages, empty = fmt.read(p)
    return [_unpose(pg) for pg in pages], fmt.kind, empty


def render_pages(pdf, numbers, store):
    paths: list[str] = []
    failed: list[int] = []
    if not shutil.which("pdftoppm"):
        return paths, "pdftoppm not found; brew install poppler"
    for n in numbers:
        prefix = store / f"{Path(pdf).stem}-p{n}"
        try:
            r = subprocess.run(["pdftoppm", "-png", "-r", "110", "-f", str(n), "-l", str(n),
                                "-singlefile", str(pdf), str(prefix)], capture_output=True, timeout=TOOL_TIMEOUT)
        except subprocess.TimeoutExpired:
            failed.append(n)
            continue
        if r.returncode == 0:
            paths.append(str(prefix) + ".png")
        else:
            failed.append(n)
    err = f"pdftoppm failed on page{'s' if len(failed) != 1 else ''} {', '.join(map(str, failed))}" if failed else ""
    return paths, err
