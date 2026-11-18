"""Reading a document into pages: pdftotext for a PDF, HTML to text, plain text chunked; a
page with no text layer rendered by pdftoppm.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import _guard as guard

from . import chunk
from . import htmltext


EMPTY_PAGE = 20          # fewer stripped chars than this and the page has no text layer

TOOL_TIMEOUT = 60       # seconds pdftotext or pdftoppm may run on one file or page


def acquire(path):
    """-> (pages: [str], kind, empty: [page numbers with no text layer]). Page numbers are 1-based."""
    p = Path(path)
    if not p.exists():
        sys.exit(f"grille: no such file: {p}")
    suffix = p.suffix.lower()
    if suffix == ".pdf":
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
        empty = [i + 1 for i, t in enumerate(pages) if len(t.strip()) < EMPTY_PAGE]
        return pages, "pdf", empty
    raw = p.read_text(errors="replace")
    if suffix in (".html", ".htm"):
        t = htmltext._Text()
        t.feed(raw)
        raw = re.sub(r"\n{3,}", "\n\n", t.text())
        return chunk._chunk_text(raw), "html", []
    return chunk._chunk_text(raw), "text", []


def render_pages(pdf, numbers, store):
    paths, failed = [], []
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
