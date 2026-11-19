"""What the screen looks for: text addressed to an automated reader, a secret asked for, a
pipe to a shell, invisible characters; one reason per pattern a passage matches.
"""
import re
import unicodedata

from . import htmltext


# The addressee nouns an injected instruction names, and the artefacts it goes after.
_AGENT = r"(?:ai|a\.i\.|artificial\s+intelligence|assistant|language\s+model|llm|large\s+language\s+model|chatbot|claude|gpt|chatgpt|copilot|gemini|automated\s+system|system\s+that\s+(?:reads|processes|reviews|summari[sz]es))"


_SECRETS = r"(?:api\s+keys?|credentials?|passwords?|passphrases?|secrets?|tokens?|private\s+keys?|\.env\b|ssh\s+keys?|login\s+details|log-in\s+details|account\s+details|session\s+cookies?)"


_INVISIBLE = "​-‏⁠-⁤﻿­\U000E0000-\U000E007F‪-‮⁦-⁩"


# Each pattern names its reason. Anchored on phrasing that addresses a model or carries a
# command, never on a word a manual uses: "as an agent for the owner", "Agent Note:",
# "New Instructions:" in a service bulletin, "do not show the operator", "Format B:" and
# "execute the following commands on the CMC" are all ordinary aviation prose and pass.
PATTERNS = [
    ("addresses an AI agent", re.compile(
        # ignore / override ... (up to three qualifiers) ... instructions / guidelines
        r"\b(?:ignore|disregard|forget|override|bypass|discard)\s+(?:\w+\s+){0,3}?(?:instructions?|prompts?|rules?|directions?|guidance|guidelines?|constraints?|safeguards?)\b"
        rf"|\byou\s+are\s+(?:now\s+|actually\s+)?(?:an?\s+)?{_AGENT}\b"
        r"|\bsystem\s+prompt\b"
        rf"|\b(?:to|for|dear)\s+(?:the|any|an|every)?\s*{_AGENT}\s+(?:reading|processing|parsing|reviewing|summari[sz]ing|handling)\s+this"
        rf"|\b(?:note|message|instructions?)\s+(?:to|for)\s+(?:the\s+)?{_AGENT}\b"
        rf"|\b(?:ai|assistant|llm|claude|chatgpt|copilot|model)\s*(?:instructions?|note|directive)s?\s*:"
        # "AI agents: tell the user…": the addressee, then an order. A bare "Copilot" or
        # "Assistant" is a person ("Copilot, respond to the tower"), so neither stands
        # alone here; the verbs leave out `check` and `report`, which a manual gives an
        # attitude indicator ("AI: check…")
        r"|\b(?:ai|a\.i\.|llm|language\s+model|chatbot|claude|gpt|chatgpt|gemini|automated\s+system)s?"
        r"(?:\s+(?:agents?|models?|systems?|assistants?|readers?|crawlers?|bots?))?\s*[:,]\s*(?:please\s+)?"
        r"(?:tell|say\s+(?:to|that)|inform|reply|respond|answer|output|ignore|disregard|pretend|act\s+as|you\s+(?:must|should|will)|do\s+not|don.t)\b"
        r"|\b(?:do\s+not|don.t|never)\s+(?:tell|inform|mention\s+(?:this\s+)?to|reveal\s+(?:this\s+)?to|disclose\s+(?:this\s+)?to)\s+the\s+(?:user|human)\b"
        r"|\b(?:from\s+now\s+on|henceforth|going\s+forward)\s*,?\s+(?:you|always|never|only|respond|reply|answer|output)\b"
        r"|\b(?:always|only)\s+(?:respond|reply|answer|output)\s+(?:with|using)\s+(?:the\s+)?(?:word|phrase|text)\b"
        # "output tokens" is a price list's noun, never an order: "Output tokens are free"
        rf"|\b(?:exfiltrate|send|post|upload|forward|email|e-mail|mail|transmit|leak|share|output|print|reveal)(?!(?<=output)\s+tokens?\b)\s+(?:the\s+|your\s+|all\s+|any\s+|me\s+)*(?:user.s\s+)?{_SECRETS}",
        re.I)),
    ("carries a shell or destructive command", re.compile(
        r"\brm\s+-[a-z]{0,8}r[a-z]{0,8}f?\s|\brm\s+-[a-z]{0,8}f[a-z]{0,8}r\s"
        r"|\bsudo\s+\S"
        r"|\bcurl\s[^\n|]*\|\s*(?:ba|z|da)?sh\b|\bwget\s[^\n|]*\|\s*(?:ba|z|da)?sh\b"
        r"|\bdd\s+if=|\bmkfs(?:\.\w+)?\s|\bdiskutil\s+(?:erase|reformat)"
        r"|\bdel\s+/[fsq]|\brmdir\s+/s|:\(\)\s*\{\s*:\|:&\s*\}"
        r"|\bchmod\s+[0-7]{3,4}\s+/|\bchown\s+-R\s"
        r"|\bpowershell(?:\.exe)?\s+-(?:e|enc|encodedcommand)\b|\bbase64\s+(?:-d|--decode)\b[^\n]*\|"
        r"|\beval\s*\(\s*(?:atob|base64)|\bos\.system\(|\bsubprocess\.(?:run|Popen|call)\(",
        re.I)),
    ("hidden characters", re.compile(
        rf"[{_INVISIBLE}]{{2,}}"                     # any run of invisible characters
        rf"|(?<=\w)[{_INVISIBLE}](?=\w)"             # or one inside a word, splitting it
        r"|[\U000E0000-\U000E007F]"                  # Unicode tag characters, never legitimate in prose
        r"|[‪-‮⁦-⁩]")),          # bidi overrides
    ("hidden from a human reader", re.compile(htmltext.HIDDEN)),   # marked by _Text; see _hides
    ("markup addressed to a model", re.compile(
        r"<\s*/?\s*(?:system|instructions?|prompt|assistant|user|tool_call|function_call|im_start|im_end)\b[^>]*>"
        r"|\[\s*(?:system|inst|/inst|assistant)\s*\]|<\|(?:im_start|im_end|system|user|assistant)\|>",
        re.I)),
]


_STRIP_INVISIBLE = re.compile(rf"[{_INVISIBLE}]")


BLOCK_CAP = 320          # a blank-line block longer than this is screened line by line


BLOCK_LINES = 4          # or with this many lines, whatever its length: a list withholds its bad item


SCAN_CAP = 8192          # characters matched at once; a longer chunk is matched in overlapping pieces

# Lookalikes folded to the Latin letter they pass for, so "Іgnоrе" (Cyrillic І, о, е) reads
# as "Ignore". Bounded to the Cyrillic and Greek letters that are drawn like Latin ones.
_CONFUSABLE = str.maketrans(
    "АВЕКМНОРСТХІЈЅаеорсухіјѕԁԛԝΑΒΕΖΗΙΚΜΝΟΡΤΥΧαεικνορτυχ",
    "ABEKMHOPCTXIJSaeopcyxijsdqwABEZHIKMNOPTYXaeiknoptux")
_FILLERS = re.compile("[\u115f\u1160\u3164\uffa0\u180e]")


def skeleton(text):
    """What a pattern matches: NFKD (full-width and styled letters to plain), invisible and
    filler characters gone, a combining mark dropped only where it rides an ASCII letter
    (so Indic, Thai and Arabic text keeps its own), lookalikes folded to Latin. Matching
    only: nothing printed is ever the skeleton."""
    out: list[str] = []
    for ch in unicodedata.normalize("NFKD", _FILLERS.sub("", text)):
        if unicodedata.category(ch) == "Mn" and out and out[-1].isascii():
            continue
        out.append(ch)
    # runs of spaces collapse, so `curl ... <9,000 spaces> | sh` is one window's width again
    return re.sub(r"[ \t]{2,}", " ", unicodedata.normalize("NFC", "".join(out)).translate(_CONFUSABLE))


def reasons_for(chunk):
    """Every pattern that fires on the chunk. The text patterns run on its skeleton, with
    the invisible characters removed, so a zero-width space inside "ignore", a full-width
    "ｉｇｎｏｒｅ" or a Cyrillic "іgnоrе" hides nothing. A chunk past SCAN_CAP is matched in
    overlapping pieces: one pattern scanning a 200 KB line from every start took 29 s."""
    if len(chunk) > SCAN_CAP:
        out = []
        for at in range(0, len(chunk), SCAN_CAP - 1024):
            out += [r for r in reasons_for(chunk[at:at + SCAN_CAP]) if r not in out]
        return out
    visible = skeleton(_STRIP_INVISIBLE.sub("", chunk))
    out = []
    for name, rx in PATTERNS:
        if rx.search(chunk if name == "hidden characters" else visible):
            out.append(name)
    return out


def _units(text):
    """Split into screening units keeping separators, so the join is byte-identical. The
    unit is the blank-line block; a block past BLOCK_CAP, which is what a dense manual
    page with no blank lines becomes, is split into lines so a withhold takes the
    offending line and its neighbours rather than the page."""
    out = []
    for part in re.split(r"(\n\s*\n)", text):
        if re.fullmatch(r"\n\s*\n", part) or (len(part) <= BLOCK_CAP and part.count("\n") < BLOCK_LINES):
            out.append(part)
        else:
            out.extend(re.split(r"(\n)", part))
    return out
