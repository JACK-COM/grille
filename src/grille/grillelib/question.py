"""Reading a prompt as questions: one question per topic part, and a prompt split only
where it cannot be one question.
"""
import re

from . import rank


_TOPIC_SEP = re.compile(r"\s*(?:[,;]|\s/\s|\band\b|\balso\b)\s*", re.I)


def topic_parts(question):
    """The parts a question strings together, where there are three or more: "accident
    summary, TPE331 service difficulty, TBO/gearbox". Syntax alone cannot tell that from
    "gross weight, empty weight, useful load", one page's worth, so sift ranks each part
    too and hints only for a part whose best page the whole question left out."""
    parts = [x.strip(" ?.") for x in _TOPIC_SEP.split(question) if x.strip(" ?.")]
    return parts if len(parts) >= 3 else []


SPLIT_MAX = 12           # past this many parts a prompt is a list of terms, not of questions


_NUMBERED = re.compile(r"(?:^|(?<=\s))\(?(\d{1,2})[).]\s+", re.M)


# an instruction, never a question's own stem: "What is the TBO: hours or years?" keeps it
_LEAD = re.compile(r"(?!\s*(?:what|which|how|when|where|who|why|is|are|does|do|can|should)\b)"
                   r"[^?:\n]{1,80}(?<!\d):\s+", re.I)


_BULLETED = re.compile(r"^\s*(?:[-*\u2022]|\d{1,2}[.)])\s+\S")


def split_prompt(prompt):
    """-> the separate questions a WebFetch-style prompt asks, or [] when it asks one.
    Splits on a numbered list that opens the prompt and counts up from 1 ("(1) ...
    (2) ..."), else on three or more semicolon-joined parts, else on two or more
    questions, else on bulleted lines; never on commas or "and", which run inside one
    topic: a five-part prompt split that way made 17 to 22 fragments. Every WebFetch
    passes through here, so a doubtful prompt stays whole: "Summarize this page; be
    brief" is one question. A lead-in ending in a colon and a space ("Quote verbatim
    every passage about: ") is dropped as an instruction, but only where it holds no
    question mark, does not end in a digit ("at 10:30") and what follows it splits."""
    m = _LEAD.match(prompt.strip())
    if m:
        parts = _split_parts(prompt.strip()[m.end():])
        if parts:
            return parts
    return _split_parts(prompt.strip())


def _split_parts(body):
    marks = list(_NUMBERED.finditer(body))
    run = []
    for m in marks:
        if int(m.group(1)) == len(run) + 1:
            run.append(m)
    lines = [x for x in body.splitlines() if x.strip()]
    if len(run) >= 2 and run[0].start() == 0:    # a list opening mid-sentence leaves its lead behind
        parts = [body[m.end():(run[k + 1].start() if k + 1 < len(run) else len(body))]
                 for k, m in enumerate(run)]
    elif body.count(";") >= 2:
        parts = body.split(";")
    elif body.count("?") >= 2:
        parts = re.split(r"(?<=\?)\s+", body)
    elif len(lines) >= 2 and all(_BULLETED.match(x) for x in lines):
        parts = [_BULLET.sub("", x) for x in lines]
    else:
        return []
    parts = [re.sub(r"^(?:and|also)\s+", "", x.strip(" \t\n;,")).strip() for x in parts]
    # every part must name something: a bare "30" or "e.g." is a fragment, not a topic
    if not all(any(w not in rank._STOP and not w.isdigit() for w in rank._words(x)) for x in parts):
        return []
    return parts if 2 <= len(parts) <= SPLIT_MAX else []


def _tags(qs):
    """[1, 2, 3] -> "questions 1, 2 and 3"."""
    nums = list(map(str, qs))
    return ("question " if len(nums) == 1 else "questions ") + (
        nums[0] if len(nums) == 1 else ", ".join(nums[:-1]) + " and " + nums[-1])


_BULLET = re.compile(r"^\s*(?:[-*>]|\d+[.)])\s*")
