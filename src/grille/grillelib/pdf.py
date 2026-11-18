"""A PDF's printed page numbers: its own /PageLabels, read by a bounded stdlib parser, else
a consistent Page N of M header or footer.
"""
import collections
import re
import zlib
from pathlib import Path


# A narrow reader for one thing, the catalog's /PageLabels number tree, because
# pdftotext counts physical pages and a reader citing a printed page number is off by
# the front matter. poppler's CLI exposes no labels and Grille takes no PDF library.
# Every failure yields no labels: an encrypted file, an inflate past the cap, a broken
# object. Known limits, each failing to no labels or to an older revision's labels:
# an object whose raw stream holds the bytes "endobj", and a predictor on an ObjStm.
# A label is page-supplied text printed outside the screen, so only a short run of
# word characters, spaces and . : / - is ever printed.
LABEL_SCAN_CAP = 64 << 20        # a larger PDF is read for text only


LABEL_INFLATE_CAP = 128 << 20    # bytes inflated from object streams, all of them together


LABEL_NODES = 4096               # number-tree nodes visited at most
OBJECT_CAP = 500_000             # object headers read at most; a real PDF of 1,500 pages has ~30k


# a printed page number: a word and a number at most ("A-12", "iv", "Index 3"), never a sentence
_LABEL_OK = re.compile(r"\w{1,10}(?:[ .:/-]\w{1,10})?")


_PDF_OBJ = re.compile(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b")


_PDF_ROOT = re.compile(rb"/Root\s+(\d+)\s+\d+\s+R\b")


_PDF_WS = b" \t\r\n\f\x00"


_PDF_DELIM = b"()<>[]{}/%"


_PDF_ESC = {ord("n"): b"\n", ord("r"): b"\r", ord("t"): b"\t", ord("b"): b"\b", ord("f"): b"\f"}


def _pdf_tokens(b):
    """Yields b"<<", b">>", b"[", b"]", ("name", "/Name"), ("str", bytes), or a bare word
    (a number or keyword) as bytes. Strings nest balanced parentheses and take every
    escape the PDF reference defines; names decode #xx; comments are skipped."""
    i, n = 0, len(b)
    while i < n:
        c = b[i]
        if c in _PDF_WS:
            i += 1
        elif c == 0x25:                                      # % comment to end of line
            while i < n and b[i] not in b"\r\n":
                i += 1
        elif b.startswith(b"<<", i) or b.startswith(b">>", i):
            yield b[i:i + 2]
            i += 2
        elif c in b"[]":
            yield bytes([c])
            i += 1
        elif c == 0x2F:                                      # /Name
            j = i + 1
            while j < n and b[j] not in _PDF_WS and b[j] not in _PDF_DELIM:
                j += 1
            raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), b[i + 1:j])
            yield ("name", "/" + raw.decode("latin-1"))
            i = j
        elif c == 0x28:                                      # (string)
            out, depth, i = bytearray(), 1, i + 1
            while i < n:
                c = b[i]
                if c == 0x5C and i + 1 < n:                  # backslash escape
                    e = b[i + 1]
                    if e in _PDF_ESC:
                        out += _PDF_ESC[e]
                        i += 2
                    elif 0x30 <= e <= 0x37:                  # \ddd, one to three octal digits
                        j = i + 1
                        while j < min(i + 4, n) and 0x30 <= b[j] <= 0x37:
                            j += 1
                        out.append(int(b[i + 1:j], 8) & 0xFF)
                        i = j
                    elif e in b"\r\n":                       # a line continuation adds nothing
                        i += 3 if b[i + 1:i + 3] == b"\r\n" else 2
                    else:
                        out.append(e)
                        i += 2
                    continue
                if c == 0x28:
                    depth += 1
                elif c == 0x29:
                    depth -= 1
                    if not depth:
                        i += 1
                        break
                out.append(c)
                i += 1
            yield ("str", bytes(out))
        elif c == 0x3C:                                      # <hex string>
            j = b.find(b">", i)
            if j < 0:
                return
            h = re.sub(rb"[^0-9A-Fa-f]", b"", b[i + 1:j])
            yield ("str", bytes.fromhex((h + b"0" * (len(h) % 2)).decode()))
            i = j + 1
        else:
            j = i
            while j < n and b[j] not in _PDF_WS and b[j] not in _PDF_DELIM:
                j += 1
            if j == i:                                       # a stray ) { or }
                i += 1
                continue
            yield b[i:j]
            i = j


def _pdf_value(t, i, depth=0):
    """-> (value, next index): dict, list, name as str, string as bytes, int or float, a
    reference as ("ref", number), or None."""
    if i >= len(t) or depth > 64:
        return None, len(t)
    x = t[i]
    if x == b"<<":
        d, i = {}, i + 1
        while i < len(t) and t[i] != b">>":
            if isinstance(t[i], tuple) and t[i][0] == "name":
                key = t[i][1]
                d[key], i = _pdf_value(t, i + 1, depth + 1)
            else:
                i += 1
        return d, i + 1
    if x == b"[":
        out, i = [], i + 1
        while i < len(t) and t[i] != b"]":
            if t[i] == b">>":
                i += 1
                continue
            v, i = _pdf_value(t, i, depth + 1)
            out.append(v)
        return out, i + 1
    if x in (b">>", b"]"):            # a missing value: leave the closer to its container
        return None, i
    if isinstance(x, tuple):
        return x[1], i + 1
    if x.isdigit() and i + 2 < len(t) and isinstance(t[i + 1], bytes) and t[i + 1].isdigit() and t[i + 2] == b"R":
        return ("ref", int(x)), i + 3
    try:
        return (float(x) if b"." in x else int(x)), i + 1
    except ValueError:
        return None, i + 1


def _pdf_parse(body):
    """The first value in an object body, read up to its stream keyword, if any."""
    toks = []
    for tok in _pdf_tokens(body or b""):
        if tok == b"stream" or len(toks) > 200_000:
            break
        toks.append(tok)
    return _pdf_value(toks, 0)[0] if toks else None


def _pdf_objects(data):
    """-> {object number: body}. Where a number is defined twice, the definition later in
    the file wins, an object packed in a stream taking its stream's position, because an
    incremental update appends. None when the object streams inflate past the cap."""
    found, streams = {}, []

    def put(num, pos, body):
        if num not in found or pos >= found[num][0]:
            found[num] = (pos, body)

    # One pass each over the object headers and the `endobj`s. A body ends at its `endobj`
    # or the next header, whichever comes first, so bodies never overlap: finding `endobj`
    # from each header, as before, copied overlapping bodies (41 KB of headers took 84 MB).
    import bisect
    heads = []
    for m in _PDF_OBJ.finditer(data):
        heads.append(m)
        if len(heads) > OBJECT_CAP:
            return None
    ends = [m.start() for m in re.finditer(rb"endobj", data)]
    for k, m in enumerate(heads):
        nxt = heads[k + 1].start() if k + 1 < len(heads) else len(data)
        e = bisect.bisect_left(ends, m.end())
        end = min(ends[e] if e < len(ends) else nxt, nxt)
        if end > m.end():
            body = data[m.end():end]
            put(int(m.group(1)), m.start(), body)
            if b"/ObjStm" in body[:1024]:
                streams.append((m.start(), body))
    budget = LABEL_INFLATE_CAP
    for pos, body in streams:
        meta = _pdf_parse(body)
        if (not isinstance(meta, dict) or meta.get("/Type") != "/ObjStm" or meta.get("/DecodeParms")
                or meta.get("/Filter") not in ("/FlateDecode", ["/FlateDecode"])):
            continue
        inflate = zlib.decompressobj()
        try:
            packed = inflate.decompress(re.split(rb"stream\r?\n", body, maxsplit=1)[-1], budget)
        except zlib.error:
            continue
        if inflate.unconsumed_tail:
            return None
        budget -= len(packed)
        try:
            first, n = int(meta["/First"]), int(meta["/N"])
            nums = list(map(int, packed[:first].split()))[:2 * n]
        except (KeyError, ValueError, TypeError):
            continue
        pairs = sorted(zip(nums[::2], nums[1::2]), key=lambda p: p[1])
        for k, (num, off) in enumerate(pairs):
            stop = pairs[k + 1][1] if k + 1 < len(pairs) else len(packed) - first
            put(num, pos, packed[first + off:first + stop])
    return {k: body for k, (_, body) in found.items()}


def _roman(n):
    out = ""
    for v, r in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
                 (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out, n = out + r, n - v
    return out


def _label(style, n):
    """The numeral for page n in a /PageLabels style, "" for none, or None where n is out
    of the style's range: roman past 3999, letters past eight repeats."""
    if style in ("/R", "/r"):
        return None if not 1 <= n <= 3999 else _roman(n).upper() if style == "/R" else _roman(n)
    if style in ("/A", "/a"):        # A..Z, then AA..ZZ, per the PDF reference
        if not 1 <= n <= 26 * 8:
            return None
        c = chr(ord("A") + (n - 1) % 26) * ((n - 1) // 26 + 1)
        return c if style == "/A" else c.lower()
    return str(n) if style == "/D" else ""


def _pdf_text(b):
    if b[:2] in (b"\xfe\xff", b"\xff\xfe"):
        return b.decode("utf-16", "replace")
    if b[:3] == b"\xef\xbb\xbf":
        return b[3:].decode("utf-8", "replace")
    return b.decode("latin-1")


def page_labels(path, count):
    """-> {physical page number: printed label} for the `count` pages pdftotext read, or {}
    when the PDF defines no labels, they match the physical numbers, or anything fails."""
    try:
        p = Path(path)
        if p.stat().st_size > LABEL_SCAN_CAP:
            return {}
        data = p.read_bytes()
        if re.search(rb"/Encrypt[\s/<]", data):     # its strings would read as noise
            return {}
        objs = _pdf_objects(data)
        if not objs:
            return {}
        roots = _PDF_ROOT.findall(data)
        cat = _pdf_parse(objs.get(int(roots[-1]))) if roots else None
        if not isinstance(cat, dict):
            cat = next((d for b in objs.values() if re.search(rb"/Type\s*/Catalog\b", b[:4096])
                        for d in [_pdf_parse(b)] if isinstance(d, dict)), None)
        if not isinstance(cat, dict) or "/PageLabels" not in cat:
            return {}

        def deref(v):
            return _pdf_parse(objs.get(v[1])) if isinstance(v, tuple) else v

        ranges, todo, seen, visits = [], [cat["/PageLabels"]], set(), 0
        while todo and visits < LABEL_NODES:          # the number tree: /Nums leaves under /Kids
            v, visits = todo.pop(), visits + 1
            if isinstance(v, tuple):
                if v[1] in seen:
                    continue
                seen.add(v[1])
                v = deref(v)
            if not isinstance(v, dict):
                continue
            nums = deref(v.get("/Nums"))
            if isinstance(nums, list):
                ranges += [(nums[k], deref(nums[k + 1])) for k in range(0, len(nums) - 1, 2)
                           if isinstance(nums[k], int) and nums[k] >= 0]
            kids = deref(v.get("/Kids"))
            if isinstance(kids, list):
                todo += kids
        ranges.sort(key=lambda r: r[0])
        out = {}
        for k, (start, spec) in enumerate(ranges):
            spec = spec if isinstance(spec, dict) else {}
            first = spec.get("/St", 1)
            if not isinstance(first, int) or not 1 <= first <= 1_000_000:
                continue
            prefix = spec.get("/P", b"")
            prefix = _pdf_text(prefix) if isinstance(prefix, bytes) else ""
            stop = ranges[k + 1][0] if k + 1 < len(ranges) else count
            for i in range(start, min(stop, count)):
                num = _label(spec.get("/S"), first + i - start)
                lab = None if num is None else prefix + num
                if lab and _LABEL_OK.fullmatch(lab):
                    out[i + 1] = lab
        return out if any(v != str(k) for k, v in out.items()) else {}
    except Exception:       # a label is a convenience; no PDF may fail a sift over it
        return {}


_PAGE_OF = re.compile(r"\bPage\s+(\d{1,5})\s+of\s+(\d{1,5})\b", re.I)


EDGE_LINES = 3           # a footer or header sits in a page's first or last three lines


def footer_labels(pages):
    """-> {physical page number: printed number} from a "Page N of M" header or footer,
    for a PDF whose printed numbers live only in its text (OHA's pwsrules.pdf: physical
    page 79 prints "Page 76 of 348"). Only where at least half the pages, and three,
    carry exactly one, nine in ten of those share one M, every N lies in 1..M, and N rises
    page by page no faster than the pages do. A page whose M differs, or whose edges
    carry two different footers, stays unlabelled (pwsrules.pdf prints "Page 315 of 349"
    once among 347 of 348); N falling, repeating or jumping ahead anywhere gives {}
    rather than a wrong number. Left open: a body line near the edge of a footerless
    page that quotes the document's own M with an N that fits."""
    found = {}
    for i, page in enumerate(pages):
        lines = [x for x in page.splitlines() if x.strip()]
        hits = {(n, m) for x in lines[:EDGE_LINES] + lines[-EDGE_LINES:]
                for n, m in _PAGE_OF.findall(x) if 1 <= int(n) <= int(m)}
        if len(hits) == 1:
            found[i + 1] = next(iter(hits))
    totals = collections.Counter(m for _, m in found.values())
    total, seen = totals.most_common(1)[0] if totals else (None, 0)
    if seen < max(3, len(pages) / 2) or seen < 0.9 * len(found):
        return {}
    found = {k: v for k, v in found.items() if v[1] == total}
    seq = [(k, int(n)) for k, (n, _) in sorted(found.items())]
    if any(not 0 < nb - na <= kb - ka for (ka, na), (kb, nb) in zip(seq, seq[1:])):
        return {}
    out = {k: str(int(n)) for k, (n, _) in found.items()}
    return out if any(v != str(k) for k, v in out.items()) else {}


def printed_numbers(path, pages):
    """The PDF's own page labels where it defines them, else a consistent footer."""
    return page_labels(path, len(pages)) or footer_labels(pages)
