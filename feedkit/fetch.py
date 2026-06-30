"""Thin networked HTTP GET for the feed worker. Conditional requests (ETag /
Last-Modified), a socket timeout, a response size cap, and an error taxonomy that
maps every failure to a short tile word. Verified on Python 3.12 / Windows: the
stdlib default TLS context verifies against the Windows cert store (no certifi),
and a 304 is RAISED as HTTPError(code=304) rather than returned."""
import ssl
import urllib.error
import urllib.request
from collections import namedtuple

from feedkit.model import build_conditional_headers

FetchResult = namedtuple(
    "FetchResult", ["status", "body", "content_type", "etag", "last_modified", "error"])

_DEFAULT_UA = "Toybox-WebFeed/1.0"


def _error_word(exc):
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 403:
            # 403 with exhausted quota = rate limit; otherwise a bad/under-scoped
            # token or missing User-Agent (GitHub returns 403 for both).
            try:
                remaining = exc.headers.get("x-ratelimit-remaining")
            except Exception:
                remaining = None
            return "rate-limited" if remaining == "0" else "bad token"
        return {401: "bad token", 404: "no access"}.get(exc.code, "http %d" % exc.code)
    if isinstance(exc, urllib.error.URLError):
        if isinstance(getattr(exc, "reason", None), ssl.SSLError):
            return "cert error"
        return "offline"
    if isinstance(exc, TimeoutError):
        return "offline"
    return "error"


def fetch(url, headers=None, etag=None, last_modified=None, timeout=12, max_bytes=1_000_000):
    request_headers = {"User-Agent": _DEFAULT_UA}
    if headers:
        request_headers.update(headers)
    request_headers.update(build_conditional_headers(etag, last_modified))
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                return FetchResult("error", None, None, None, None, "too large")
            return FetchResult("ok", body, response.headers.get("Content-Type"),
                               response.headers.get("ETag"),
                               response.headers.get("Last-Modified"), None)
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return FetchResult("not_modified", None, None, etag, last_modified, None)
        return FetchResult("error", None, None, None, None, _error_word(exc))
    except (urllib.error.URLError, TimeoutError) as exc:
        return FetchResult("error", None, None, None, None, _error_word(exc))
