"""Ranking pages against a question: by meaning through the embedder, by word overlap when
none answers, and exact phrases lifted.
"""
import http.client
import re

import _embed as embed
import _guard as guard

from . import config
from . import patterns
from . import vcache


# Ten, not eight: on 123 paraphrased questions over five aircraft PDFs, EmbeddingGemma 2
# put the answering page in its top ten 86 times, where nomic-embed-text's top eight held
# it 84 times; the two pages cost about 1k input tokens a question. One model then serves
# every Panoply piece. Smaller sub-chunks and fusing word overlap both failed to close it.
PAGES_DEFAULT = 10


SUBCHUNK = 1800          # a -layout page runs 3-5k chars; the embedder cuts a text at 2000


MIN_SCORE_NOTE = 0.35    # below this the best page is reported as weak, still returned


_STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "what", "how",
         "does", "with", "at", "by", "from", "this", "that", "it", "its", "are", "be", "any",
         "about", "all", "every", "text", "passage", "passages", "quote", "verbatim"}


def words(s):
    return re.findall(r"[a-z0-9]+", s.lower())


def _overlap(q, page):
    """Word-overlap fallback when no embedder is reachable: fraction of the question's
    content words that appear on the page. Cannot see a paraphrase, and says so."""
    qw = {w for w in words(q) if w not in _STOP and len(w) > 2}
    if not qw:
        return 0.0
    pw = set(re.findall(r"[a-z0-9]+", page.lower()))
    return len(qw & pw) / len(qw)


def rank_each(questions, pages, deadline=None):
    """-> ([[(page_index, score)] per question], method). Each page is embedded once, in
    sub-chunks, and takes its best sub-chunk's score against each question, so the bottom
    half of a long page is not invisible and a third question costs one query vector."""
    try:
        docs, owner = [], []
        for i, page in enumerate(pages):
            body = page.strip()
            if not body:
                continue
            for j in range(0, len(body), SUBCHUNK):
                docs.append(body[j:j + SUBCHUNK])
                owner.append(i)
        # bare text: the model's retrieval prompts never beat it here, nor on Locket's task
        cache = vcache.open_cache(config.home())
        try:
            # each request waits at most what the deadline leaves; a page read before costs nothing
            wait = deadline.cap(embed.TIMEOUT) if deadline else embed.TIMEOUT
            if deadline:
                deadline.check("ranking")
            texts, vecs = list(questions) + docs, []
            for at in range(0, len(texts), 256):    # the deadline between slices, not once
                if deadline:
                    deadline.check("ranking")
                    wait = deadline.cap(embed.TIMEOUT)
                with embed.settings(TIMEOUT=wait):
                    vecs += embed.embed(texts[at:at + 256], quiet=True, cache=cache)
        finally:
            if cache:
                cache.close()
        qvs, dv = vecs[:len(questions)], embed.normalise(vecs[len(questions):])
        bests = []
        for qv in qvs:
            best: dict[int, float] = {}
            for i, s in zip(owner, embed.cosines(qv, dv).tolist()):
                if s > best.get(i, -1.0):
                    best[i] = s
            bests.append(best)
        method = f"embedding ({embed.resolve_backend()[1]})"
    except (RuntimeError, OSError, TimeoutError, ValueError, TypeError, KeyError, http.client.HTTPException) as e:
        # no embedder, a reply that is not one, or no time left: degrade, and say so
        bests = [{i: _overlap(q, p) for i, p in enumerate(pages) if p.strip()} for q in questions]
        reason = guard.relay((str(e).splitlines() or [""])[0], 80)
        method = f"word overlap (no embedder: {'its message withheld' if patterns.reasons_for(reason) else reason})"
    flat: dict[int, str] = {}           # page index -> its words, joined
    orders, lifted = [], False
    for q, b in zip(questions, bests):
        plain = sorted(b.items(), key=lambda kv: -kv[1])
        hits = _phrase_hits(q, pages, b, flat)
        order = sorted(plain, key=lambda kv: kv[0] not in hits)     # stable: score orders each tier
        lifted = lifted or order != plain
        orders.append(order)
    if lifted:
        method += ", pages holding a question's exact word pair first"
    return orders, method


def _phrase_hits(q, pages, scored, flat):
    """The pages holding one of the question's adjacent content-word pairs verbatim
    ("pitch trim", "steel tube"). Embedding order put a Wikipedia infobox above the one
    passage naming "pitch trim", which a grep of the same file found in one call, so a
    page with an exact pair ranks ahead of any page without one. A long question has many
    pairs and most pages hit one, so its order falls back to score. `flat` caches each
    page's words, joined, across questions."""
    w = words(q)
    pairs = {f" {x} {y} " for x, y in zip(w, w[1:])
             if x not in _STOP and y not in _STOP and len(x) > 1 and len(y) > 1}
    if not pairs:
        return set()
    for i in scored:
        if i not in flat:
            flat[i] = f" {' '.join(words(pages[i]))} "
    return {i for i in scored if any(p in flat[i] for p in pairs)}


def rank(question, pages):
    """-> ([(page_index, score)], method) for one question."""
    orders, method = rank_each([question], pages)
    return orders[0], method


def interleave(orders, budget):
    """-> [(page_index, score, [question numbers])], at most `budget` pages. The questions
    take turns, each claiming its best page not yet taken, so no one question's pages
    crowd out another's. A page a later question also ranks within the pages it would
    have claimed is tagged with that question too, rather than taken twice."""
    taken: dict[int, list] = {}         # page index -> its pick, [index, score, question numbers]
    picks: list[list] = []
    cursor = [0] * len(orders)
    while len(picks) < budget and any(c < len(o) for c, o in zip(cursor, orders)):
        for q, order in enumerate(orders):
            if len(picks) >= budget:
                break
            while cursor[q] < len(order) and order[cursor[q]][0] in taken:
                taken[order[cursor[q]][0]][2].append(q + 1)
                cursor[q] += 1
            if cursor[q] < len(order):
                i, sc = order[cursor[q]]
                taken[i] = [i, sc, [q + 1]]
                picks.append(taken[i])
                cursor[q] += 1
    return [(i, sc, sorted(set(qs))) for i, sc, qs in picks]
