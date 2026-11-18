"""Fetching a URL: the bounded download, its kind and charset, the saved copy, and verify's
quick check that a URL answers.
"""
import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


FETCH_CAP = 64 * 1024 * 1024   # the largest manual WebFetch has saved here is 10 MB


FETCH_TIMEOUT = 30


VERIFY_TIMEOUT = 15


REDIRECT_CAP = 8


USER_AGENT = "grille/1 (document sieve; python-urllib)"


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Counts hops, refuses a hop off http (urllib itself already refuses file: and the
    like; this catches ftp:), stops at REDIRECT_CAP, and pins the method across hops as a
    belt beside urllib's own HEAD-keeping. `timeout` is per hop, so a chain can take
    REDIRECT_CAP times it."""

    def __init__(self):
        super().__init__()
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme not in ("http", "https"):
            raise urllib.error.URLError(f"redirect to a non-http address refused: {newurl}")
        self.count += 1
        if self.count > REDIRECT_CAP:
            raise urllib.error.URLError(f"more than {REDIRECT_CAP} redirects")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.method = req.get_method()
        return new


def _opener(*handlers):
    """urllib's opener with proxies from the environment only (HTTP_PROXY, HTTPS_PROXY,
    NO_PROXY). The default also asks macOS's SystemConfiguration, and after that lookup on a
    plain-http fetch every child this process starts died of SIGSEGV before exec: pdftotext
    on the fetched PDF, the scorer, a fallback command. Measured under Python 3.9 and 3.14."""
    return urllib.request.build_opener(urllib.request.ProxyHandler(urllib.request.getproxies_environment()),
                                       *handlers)


def _open(url, method, timeout):
    """-> (response, redirect handler). Raises ValueError off http, URLError on the wire,
    HTTPError on a 4xx/5xx (the response is on the error)."""
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"only http and https are fetched: {url}")
    rh = _Redirects()
    req = urllib.request.Request(url, method=method,
                                 headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    return _opener(rh).open(req, timeout=timeout), rh


def fetch(url, cap=FETCH_CAP, timeout=FETCH_TIMEOUT):
    """-> (data, final_url, content_type, charset, redirects). Refuses a body over `cap`
    bytes, by Content-Length where the server sends one and by count where it does not."""
    resp, rh = _open(url, "GET", timeout)
    with resp:
        length = resp.headers.get("Content-Length", "")
        if length.isdigit() and int(length) > cap:
            raise ValueError(f"{int(length)} bytes is over the {cap} byte cap")
        buf = bytearray()
        while chunk := resp.read(1 << 16):
            buf += chunk
            if len(buf) > cap:
                raise ValueError(f"body is over the {cap} byte cap")
        return (bytes(buf), resp.geturl(), resp.headers.get_content_type(),
                resp.headers.get_content_charset(), rh.count)


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
        path.write_text(_decode(data, charset))
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
            resp, rh = _open(url, method, timeout)
            with resp:
                row.update(status=resp.status, final=resp.geturl(),
                           type=resp.headers.get_content_type(), redirects=rh.count,
                           dropped_path=dropped_path(url, resp.geturl()))
            return row
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:   # a followed redirect never lands here: this one was refused
                row["error"] = f"HTTP {e.code}: {e.reason}"
                return row
            if method == "HEAD":
                continue          # many hosts refuse HEAD and serve GET; GET is the ground truth
            row.update(status=e.code, final=e.geturl(), type=e.headers.get_content_type(),
                       dropped_path=dropped_path(url, e.geturl()))
            return row
        except (urllib.error.URLError, ValueError, OSError) as e:
            row["error"] = str(getattr(e, "reason", None) or e)
            return row
    return row
