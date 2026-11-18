"""Fetching a URL: the bounded download, its kind and charset, the saved copy, and verify's
quick check that a URL answers.
"""
import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import _guard as guard
import _web as web


FETCH_CAP = 64 * 1024 * 1024   # the largest manual WebFetch has saved here is 10 MB


FETCH_TIMEOUT = 30


VERIFY_TIMEOUT = 15


REDIRECT_CAP = 8


USER_AGENT = "grille/1 (document sieve; python-urllib)"


Redirected = web.Redirected          # another origin: reported, never followed
Inward = web.Inward                  # a hop from a public origin into a private address


def _open(url, method, timeout, deadline=None, follow="same-origin"):
    """-> the response. Raises ValueError off http, Redirected for a hop to another origin
    (follow="same-origin"), Inward for one from a public origin into this machine's own or a
    private network, URLError on the wire, HTTPError on a 4xx/5xx."""
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"only http and https are fetched: {guard.relay(url, 200)}")
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    # a page the agent asked for by name may be local; a hop it did not ask for may not
    public = guard.public_address(urllib.parse.urlsplit(url).hostname or "")
    return web.open_url(req, timeout, deadline=deadline, follow=follow, guard_private=public, hops=REDIRECT_CAP)


def fetch(url, cap=FETCH_CAP, timeout=FETCH_TIMEOUT, deadline=None):
    """-> (data, final_url, content_type, charset, redirected). Refuses a body over `cap`
    bytes, by Content-Length where the server sends one and by count where it does not, and
    a fetch past `deadline` (else `timeout` over the whole fetch, every hop and read)."""
    deadline = deadline or web.Deadline(timeout)
    resp = _open(url, "GET", timeout, deadline)
    with resp:
        length = resp.headers.get("Content-Length", "")
        if length.isdigit() and int(length) > cap:
            raise ValueError(f"{int(length)} bytes is over the {cap} byte cap")
        data = web.read(resp, cap, deadline)
        final = resp.geturl()
        return (data, final, resp.headers.get_content_type(), resp.headers.get_content_charset(),
                int(final != url))


def _kind_of(data, ctype):
    """An explicit content type is trusted; the body is sniffed only where the server said
    nothing useful, so a text/plain excerpt that shows HTML markup stays text."""
    if data[:5] == b"%PDF-" or ctype == "application/pdf":
        return "pdf"
    if ctype in ("text/html", "application/xhtml+xml"):
        return "html"
    if ctype in ("", "application/octet-stream"):
        head = data[:2048].lower()
        if b"<html" in head or b"<!doctype html" in head:
            return "html"
    return "text"


_META_CHARSET = re.compile(rb"""<meta[^>]+charset=["']?\s*([\w.:-]+)""", re.I)


def _decode(data, charset):
    """Header charset first, then a <meta charset> in the first kilobyte, then UTF-8. A
    charset the header names but Python lacks (get_content_charset does not validate it)
    falls through rather than crashing."""
    m = _META_CHARSET.search(data[:1024])
    for enc in (charset, m.group(1).decode("ascii", "ignore") if m else None, "utf-8"):
        if enc:
            try:
                return data.decode(enc, errors="replace")
            except LookupError:
                continue
    return data.decode("utf-8", errors="replace")


def save_fetched(url, data, ctype, charset, store):
    """Write the body into the session store under a name acquire() can type, and return
    (path, kind). Text is re-encoded as UTF-8 so acquire reads it without a charset."""
    kind = _kind_of(data, ctype)
    base = re.sub(r"[^\w.-]+", "_", Path(urllib.parse.urlsplit(url).path).name)[:60] or "page"
    base = re.sub(r"\.(pdf|html?|txt)$", "", base, flags=re.I)
    path = store / f"fetch-{hashlib.sha1(url.encode()).hexdigest()[:10]}-{base}.{kind if kind != 'text' else 'txt'}"
    if kind == "pdf":
        path.write_bytes(data)
    else:
        path.write_text(_decode(data, charset), encoding="utf-8")
    return path, kind


def dropped_path(url, final):
    """True when a redirect took a request for a document to the bare root of a site, the
    shape of a bot wall, a login wall or a missing page sent home: the body is not the page."""
    def root(u):
        return not urllib.parse.urlsplit(u).path.strip("/")
    return final is not None and not root(url) and root(final)


DROPPED = "redirected to the root of a site, so this is probably a wall or a homepage, not the page asked for"


def verify(url, timeout=VERIFY_TIMEOUT):
    """-> one row per URL: status, final address, content type, redirects, error. HEAD
    first; a server that answers HEAD with an error gets one GET, whose body is never read."""
    row = {"url": url, "status": None, "final": None, "type": None, "redirects": 0,
           "dropped_path": False, "error": None}
    for method in ("HEAD", "GET"):
        try:
            # verify reads no body, so it follows a hop to another origin, never into a private address
            resp = _open(url, method, timeout, web.Deadline(timeout), follow="any")
            with resp:
                row.update(status=resp.status, final=resp.geturl(),
                           type=resp.headers.get_content_type(), redirects=int(resp.geturl() != url),
                           dropped_path=dropped_path(url, resp.geturl()))
            return row
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:   # a followed redirect never lands here: this one was refused
                row["error"] = f"HTTP {e.code}: {guard.relay(e.reason, 120)}"
                return row
            if method == "HEAD":
                continue          # many hosts refuse HEAD and serve GET; GET is the ground truth
            row.update(status=e.code, final=e.geturl(), type=e.headers.get_content_type(),
                       dropped_path=dropped_path(url, e.geturl()))
            return row
        except (urllib.error.URLError, ValueError, OSError, TimeoutError) as e:
            row["error"] = guard.relay(getattr(e, "reason", None) or e, 300)
            return row
    return row
