"""Reading a document into pages: pdftotext for a PDF, HTML to text, a Word document's body
text, plain text chunked; a page with no text layer rendered by pdftoppm. A binary body no
format claims is refused.
"""
import codecs
import re
import shutil
import subprocess
import sys
import xml.parsers.expat
import zipfile
import zlib
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
    return chunk.chunk_text(re.sub(r"\n{3,}", "\n\n", t.text())), []


def _app_shell(data, text):
    t = htmltext._Text()
    t.feed(text)
    if len(t.text(chrome=True).strip()) < htmltext.APP_SHELL and b"<script" in data.lower():
        return ("this page carries scripts and almost no text: a JavaScript app renders "
                "nothing here, so read it in the browser")
    return None


BINARY_PROBE = 8192      # bytes looked at for a NUL, as git decides a file is binary


def is_binary(text):
    """True for a body no text reader should pass on: a NUL in its first BINARY_PROBE
    characters once decoded. TEXT takes whatever no other format claims, so without this a
    zip, an image or an Office file reaches the pages as noise that looks read. Judged after
    decoding, because UTF-16 text carries NULs as bytes and none as characters."""
    return "\x00" in text[:BINARY_PROBE]


def reads():
    return ", ".join(f.kind for f in FORMATS)


def _read_text(p):
    data = p.read_bytes()
    bom16 = data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
    text = data.decode("utf-16" if bom16 else "utf-8", errors="replace")
    if is_binary(text):
        sys.exit(f"grille: {p} is binary, not text; grille reads {reads()}")
    return chunk.chunk_text(text), []


DOCX_CAP = 64 * 1024 * 1024   # bytes of word/document.xml parsed, counted as read, so a lying header changes nothing
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DOCX_TEXT = {_W + "tab": "\t", _W + "br": "\n", _W + "cr": "\n", _W + "noBreakHyphen": "-"}


class _Refused(Exception):
    pass


def _read_docx(p):
    """The body text of word/document.xml: runs in order, a tab as a tab, a break as a
    newline, a blank line after each paragraph. Parsed by expat with namespaces resolved, so
    a rebound prefix or a UTF-16 part reads the same, and streamed against DOCX_CAP. A DTD is
    refused outright: a Word body never declares one, and that is where entity expansion
    lives. Deleted text, field codes, headers, footers, footnotes and comments are left out;
    a text box Word writes twice (mc:Choice and mc:Fallback) is read twice, which hides
    nothing from the screen."""
    out: List[str] = []
    stack: List[str] = []
    parser = xml.parsers.expat.ParserCreate(namespace_separator="}")
    parser.buffer_text = True

    def refuse(*_):
        raise _Refused

    def start(name, _attrs):
        parent = stack[-1] if stack else ""
        stack.append(name)
        if name in _DOCX_TEXT and parent == _W + "r":     # a w:tab under w:tabs is a tab stop, not text
            out.append(_DOCX_TEXT[name])

    def end(name):
        stack.pop()
        if name == _W + "p":
            out.append("\n\n")

    def chars(data):
        if stack and stack[-1] == _W + "t":
            out.append(data)

    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    why = ""
    try:
        with zipfile.ZipFile(p) as z:
            if "word/document.xml" not in z.namelist():
                sys.exit(f"grille: {p} is a zip without word/document.xml, so not a Word document")
            seen = 0
            with z.open("word/document.xml") as f:
                while block := f.read(1024 * 1024):
                    seen += len(block)
                    if seen > DOCX_CAP:
                        sys.exit(f"grille: {p} unzips past {DOCX_CAP // (1024 * 1024)} MB; refused")
                    parser.Parse(block, False)
            parser.Parse(b"", True)
    except (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError):
        why = "is not a readable zip (damaged, encrypted or compressed a way Python cannot read)"
    except _Refused:
        why = "declares a DTD, which a Word document never does; refused"
    except xml.parsers.expat.ExpatError as e:
        why = f"holds a word/document.xml that is not well-formed XML ({xml.parsers.expat.ErrorString(e.code)})"
    if why:
        sys.exit(f"grille: {p} {why}")
    return chunk.chunk_text(re.sub(r"\n{3,}", "\n\n", "".join(out))), []


PDF = Format("pdf", (".pdf",), ("application/pdf",), _read_pdf, unit="page",
             sniff=lambda head: head[:5] == b"%PDF-", labels=lambda path, pages: pdf.printed_numbers(path, pages),
             binary=True, ext="pdf")
HTML = Format("html", (".html", ".htm"), ("text/html", "application/xhtml+xml"), _read_html,
              sniff=lambda head: b"<html" in head.lower() or b"<!doctype html" in head.lower(), ext="html",
              note=_app_shell)
DOCX = Format("docx", (".docx",), ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
              _read_docx, sniff=lambda head: head[:4] == b"PK\x03\x04" and b"word/" in head,
              binary=True, ext="docx")
TEXT = Format("text", (), (), _read_text)
FORMATS = (PDF, HTML, DOCX, TEXT)     # TEXT last: whatever no other format claims, refusing a binary body


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
