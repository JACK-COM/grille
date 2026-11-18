"""The screen: each passage a pattern flags is held in the session's store behind an id and
replaced by a placeholder naming why.
"""
import hashlib
import json
import re

from . import patterns


def screen(text, source, page_no, store):
    """-> (screened_text, withheld: [{id, reasons, lines}]). A unit carrying a match is
    replaced by one placeholder line and written to the store by id. In a line-split
    block the line either side of a hit is withheld with it, because an instruction
    rarely fits one line and the neighbour is usually its continuation."""
    parts = patterns._units(text)
    hit = [bool(p.strip()) and not re.fullmatch(r"\n\s*\n", p) and bool(patterns.reasons_for(p)) for p in parts]
    # neighbours of a hit inside a line-split block: parts separated by a bare "\n"
    take = list(hit)
    for k, h in enumerate(hit):
        if not h:
            continue
        for j in (k - 2, k + 2):
            if 0 <= j < len(parts) and parts[k - 1 if j < k else k + 1] == "\n" and parts[j].strip():
                take[j] = True
    withheld, out, k = [], [], 0
    while k < len(parts):
        if not take[k]:
            out.append(parts[k])
            k += 1
            continue
        # merge a run of taken parts (and the newlines between them) into one span
        j = k
        while j + 2 < len(parts) and parts[j + 1] == "\n" and take[j + 2]:
            j += 2
        span = "".join(parts[k:j + 1])
        line, held = hold(span, patterns.reasons_for(span) or ["neighbour of a withheld line"], source, page_no, store)
        out.append(line)
        withheld.append(held)
        k = j + 1
    return "".join(out), withheld


def hold(span, reasons, source, page_no, store):
    """Write a span to the store by id -> (placeholder line, {id, reasons, lines})."""
    wid = hashlib.sha1(f"{source}|{page_no}|{span}".encode()).hexdigest()[:8]
    (store / f"{wid}.json").write_text(json.dumps({
        "id": wid, "source": str(source), "page": page_no,
        "reasons": reasons, "text": span}, indent=1))
    n = span.count("\n") + 1
    line = (f"[grille: withheld {n} line{'s' if n != 1 else ''} on p.{page_no}: "
            f"{'; '.join(reasons)}. id={wid}; `grille show {wid}` to read it]")
    return line, {"id": wid, "reasons": reasons, "lines": n}


_PLACEHOLDER = re.compile(r"^\[grille: withheld .*\]$", re.M)
