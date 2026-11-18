"""HTML to text: the words a reader sees, hidden text marked, links carried as text (href),
page chrome dropped.
"""
import html.parser
import re
import textwrap
import urllib.error
import urllib.parse
import urllib.request


APP_SHELL = 200          # fewer text chars than this beside a <script> and the page is a JS app


HIDDEN = ""        # private-use mark on each line a human reader would not see


COMMENT_WORDS = 6        # an HTML comment with this many words is prose, not markup


HIDDEN_WRAP = 400       # a hidden run is marked in pieces this long, so no later split drops the mark


# hrefs left out of the text: an anchor, a script, inline data or a contact names no document
LINK_SKIP = ("#", "javascript:", "mailto:", "data:", "tel:", "sms:", "blob:")


LINK_WORDS = 12          # an href decoding to this many words is prose; a %20 filename runs to ~10


# Inline styles that hide text from a human reader, read with whitespace removed. Only the
# element's own style is read: a stylesheet class that hides text is not resolved, so the
# screen still reads that by content. The sr-only pattern (a 1px box clipped to nothing)
# is caught too, though a screen reader voices it: text a sighted reader never sees is
# where a planted line lives, and withholding a "Skip to content" costs one line.
_TERMINAL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")


def printable(text):
    """`text` as it may reach a terminal: every control but newline and tab, and every bidi
    override, a space. An escape sequence in a page would otherwise retitle, clear or
    conceal on the reader's terminal."""
    return _TERMINAL.sub(" ", text)


class _Run:
    """A block of hidden lines, kept as a list while the page is parsed: re-joining the block
    for each hidden element made a page of `<span hidden>a</span>` quadratic."""

    def __init__(self, lines):
        self.lines = lines

    def __str__(self):
        return "\n\n" + "\n".join(self.lines) + "\n\n"


STYLE_CAP = 2000
DEPTH_CAP = 256          # open elements tracked; deeper nesting is read as text, its tags ignored
_HIDING_STYLE = re.compile(
    r"display:none|opacity:0(?:\.0+)?(?:;|$)"
    r"|font-size:0+(?:\.0+)?(?:px|pt|em|rem|%)?(?:;|$)|font-size:(?:0?\.\d+|1)(?:px|pt)"
    r"|font-size:0?\.0\d*(?:em|rem)|font-size:\d(?:\.\d+)?%"
    r"|(?:^|;)color:(?:transparent|rgba\([^)]*,0(?:\.0+)?\)|hsla\([^)]*,0(?:\.0+)?\))"
    r"|(?:left|top|text-indent|margin-left):-\d{3,}(?:px|em|rem)"
    r"|clip:rect\(0(?:px)?,?0(?:px)?,?0(?:px)?,?0(?:px)?\)"
    r"|clip-path:inset\((?:50|[5-9]\d|100)%|clip-path:(?:circle|ellipse)\(0"
    r"|(?:max-)?height:0(?:px)?(?:;|$).*overflow:hidden|overflow:hidden.*(?:max-)?height:0(?:px)?(?:;|$)")


def _hides(attrs):
    """How an element's own attributes hide its text from a human reader: "hard" for the
    `hidden` attribute, a hiding inline style or text coloured like its own background,
    none of which a descendant can undo; "soft" for `visibility:hidden`, which a
    descendant's `visibility:visible` does undo, and "shown" for that; else None.
    `aria-hidden` is not one: it hides from a screen reader what a sighted reader sees.
    Nor is a tab panel closed by `hidden` or `display:none`, which a reader opens with a
    click: a code-tab widget hides every panel but the first that way. `hidden="until-found"`
    still counts, since only find-in-page opens it; so does any other hiding on a tab
    panel, and its text still goes through the pattern screen."""
    a = dict(attrs)
    tab = (a.get("role") or "").strip().lower() == "tabpanel"
    if "hidden" in a and not (tab and (a["hidden"] or "").strip().lower() != "until-found"):
        return "hard"
    # a style attribute is short; a 180 KB one is a page making the patterns below slow
    style = re.sub(r"\s+", "", (a.get("style") or "")[:STYLE_CAP].lower()).replace("!important", "")
    if _HIDING_STYLE.search(style.replace("display:none", "") if tab else style):
        return "hard"
    fg = re.search(r"(?:^|;)color:([^;]+)", style)
    bg = re.search(r"background(?:-color)?:([^;]+)", style)
    if fg and bg and fg.group(1) == bg.group(1):
        return "hard"
    vis = re.findall(r"visibility:(hidden|visible|collapse)", style)
    if vis:
        return "shown" if vis[-1] == "visible" else "soft"
    return None


class _Text(html.parser.HTMLParser):
    """Visible text, with page chrome held apart: a site's menus outranked its content on
    one manufacturer's support page. `nav` and a navigation/banner/contentinfo/complementary role
    are chrome anywhere; `header`, `footer` and `aside` only outside `main` and `article`,
    where they hold an article's own title, byline or callout.

    html.parser does no HTML5 error recovery, so open elements are kept on a stack and an
    end tag closes back to its nearest match, closing whatever was left open inside it,
    but never reaches past a chrome element: only the chrome element's own end tag closes
    it. `main`, which HTML forbids inside chrome, ends every chrome element open around
    it. Text counts as chrome only under an element that was ended, so one left open to
    the end of the page leaks its menu rather than taking the page with it. A `header`,
    `footer` or `aside` held as content counts as chrome after all when no `main` or
    `article` around it was ended by its own end tag: an article never closed would
    otherwise hold the page's own footer as its byline."""
    SKIP = {"script", "style", "noscript", "template", "svg"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section",
             "article", "header", "footer", "table", "pre", "blockquote", "nav", "aside", "main"}
    CHROME_ROLES = {"navigation", "banner", "contentinfo", "complementary"}
    PAGE_CHROME = {"header", "footer", "aside"}
    CONTENT = {"main", "article"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
            "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self._skip = [], 0        # out: (text, chrome frames open around it)
        self._deep = 0                      # elements opened past DEPTH_CAP, untracked
        # [tag, is_chrome, is_content, ended, hides, shields, link] per open element; shields
        # are the content frames that hold a header, footer or aside as content, and link is
        # an <a>'s (href, index into out where its text starts)
        self._open = []

    def _in_chrome(self, frames=None):
        return tuple(f for f in (self._open if frames is None else frames) if f[1] or f[5])

    @staticmethod
    def _held(f):
        """Whether text under this frame is chrome, judged once the page is parsed."""
        return f[3] and not any(c[3] for c in f[5])

    def handle_starttag(self, tag, attrs):
        if len(self._open) >= DEPTH_CAP:
            # every event walks the open elements, so unclosed tags made a page quadratic:
            # 80 KB of `<i>a` took 17 s. Past the cap no element is tracked, so nothing can
            # say what is hidden or a script: every word below is withheld, and scripts skipped.
            self._deep += 1
            if tag in self.SKIP:
                self._skip += 1
            return
        if tag not in self.VOID:            # never closed, so never pushed
            if tag == "main":
                for f in self._open:
                    f[3] = f[3] or f[1]
                    f[1] = False
            role = (dict(attrs).get("role") or "").strip().lower()
            content = [f for f in self._open if f[2]]
            chrome = (tag == "nav" or role in self.CHROME_ROLES
                      or (tag in self.PAGE_CHROME and not content))
            shields = content if tag in self.PAGE_CHROME and not chrome else []
            # a link inside eight open links is text: each one re-joins all text after it
            link = ((dict(attrs).get("href") or "").strip(), len(self.out)) \
                if tag == "a" and sum(1 for f in self._open if f[6]) < 8 else None
            self._open.append([tag, chrome, tag in self.CONTENT, False, _hides(attrs), shields, link])
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.out.append(("\n", self._in_chrome()))

    def _hidden(self, text):
        """Text a human reader never sees, marked on every line so the screen withholds it
        whatever it says: a planted line that avoids every pattern is still hidden."""
        # every piece carries the mark: one long hidden line cut by _split_long would
        # otherwise leave its tail unmarked beside ordinary prose
        lines = [HIDDEN + piece for ln in text.strip().splitlines()
                 for piece in (textwrap.wrap(ln, HIDDEN_WRAP) or [""])]
        chrome = self._in_chrome()
        last = self.out[-1] if self.out else None
        if last is not None and last[1] == chrome and isinstance(last[0], _Run):
            last[0].lines += lines              # one hidden run, one block: extended, not rebuilt
        else:
            self.out.append((_Run(lines), chrome))

    def _is_hidden(self, frames=None):
        """Whether text here is hidden: a hard hider anywhere above, or the nearest
        visibility setting saying hidden."""
        state = False
        for f in (self._open if frames is None else frames):
            if f[4] == "hard":
                return True
            if f[4] in ("soft", "shown"):
                state = f[4] == "soft"
        return state

    def handle_comment(self, data):
        # markup comments (`/wp:paragraph`, `[if IE]`) are dropped; one written as prose
        # is withheld like hidden text, so a planted comment leaves a trace a reader can see
        if not self._skip and len(re.findall(r"[A-Za-z]{2,}", data)) >= COMMENT_WORDS:
            self._hidden(data)

    def _link(self, d):
        """Writes the href of the closing <a> at depth d after its text, as `text (href)`, kept
        as the page wrote it: sift reads a saved file and never knows the page's URL. A reader
        never sees an href, so one that decodes to prose is withheld like a hidden comment."""
        frames = self._open[:d + 1]         # the link's own chrome and hiding, not its children's
        href, start = frames[-1][6]
        text = " ".join("".join(str(t) for t, _ in self.out[start:]).split())
        # browsers drop control characters and spaces in a scheme, so `java\tscript:` is a script
        if (not href or re.sub(r"[\x00-\x20]", "", href).lower().startswith(LINK_SKIP)
                or href == text or self._skip or self._is_hidden(frames)):
            return
        words = urllib.parse.unquote_plus(href).split()
        if len(words) >= LINK_WORDS:
            self._hidden(" ".join(words))
        else:
            from . import patterns          # patterns reads this module's HIDDEN mark
            if patterns.reasons_for(" ".join(words)):
                # screened as it reads decoded: `%20` would otherwise hide every space a pattern needs
                self._hidden(" ".join(words))
            else:
                self.out.append((f" ({' '.join(href.split())})", self._in_chrome(frames)))

    def handle_endtag(self, tag):
        if self._deep:
            self._deep -= 1
            if tag in self.SKIP and self._skip:
                self._skip -= 1
            return
        k = None
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == tag:     # a stray end tag with no match closes nothing
                k = i
                break
            if self._open[i][1]:            # nor does one reaching past a chrome element:
                break                       # a real site's nav held a surplus </div>
        if k is not None:                   # every <a> this closes, its own or one left open inside
            for d in range(len(self._open) - 1, k - 1, -1):
                if self._open[d][6]:
                    self._link(d)
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.out.append(("\n", self._in_chrome()))
        if k is not None:
            self._open[k][3] = True
            del self._open[k:]


    def handle_data(self, data):
        if self._skip:
            return
        if self._deep or self._is_hidden():
            if data.strip():
                self._hidden(data)
            return
        self.out.append((data, self._in_chrome()))

    def text(self, chrome=False):
        """The page's text without its chrome, or with it when asked. A page whose text is
        nearly all chrome is returned whole rather than empty."""
        body = "".join(str(t) for t, fs in self.out if chrome or not any(self._held(f) for f in fs))
        if not chrome and len(body.strip()) < APP_SHELL:
            return self.text(chrome=True)
        return body
