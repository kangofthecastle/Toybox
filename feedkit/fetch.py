"""Thin networked HTTP GET for the feed worker. Conditional requests (ETag /
Last-Modified), a socket timeout, a response size cap, and an error taxonomy that
maps every failure to a short tile word. Verified on Python 3.12 / Windows: the
stdlib default TLS context verifies against the Windows cert store (no certifi),
and a 304 is RAISED as HTTPError(code=304) rather than returned."""
import ssl
import time
import urllib.error
import urllib.request
from collections import namedtuple

from feedkit.model import build_conditional_headers

FetchResult = namedtuple(
    "FetchResult",
    ["status", "body", "content_type", "etag", "last_modified", "error", "poll_interval"],
    defaults=(None,))

SendResult = namedtuple("SendResult", ["status", "code", "error"], defaults=(None, None))

_DEFAULT_UA = "Toybox-WebFeed/1.0"

# Error words worth one immediate retry: only the transient network class. A
# dropped packet / momentary DNS hiccup / a spike past the socket timeout maps to
# "offline"; retrying once usually rides over it. Deterministic failures (HTTP
# status words, "too large", "cert error") are NOT retried -- a second identical
# request would fail identically and only waste the worker's time.
_RETRYABLE_ERRORS = ("offline",)
_RETRY_DELAY_S = 0.5   # brief pause before the single retry, so a blip has cleared


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


def _poll_interval(response):
    """The server's requested minimum seconds between polls (GitHub's
    X-Poll-Interval), or None when absent / non-integer."""
    try:
        return int(response.headers.get("X-Poll-Interval"))
    except (TypeError, ValueError):
        return None


def fetch(url, headers=None, etag=None, last_modified=None, timeout=12,
          max_bytes=2_000_000, retries=1, retry_delay=_RETRY_DELAY_S):
    """Conditional HTTP GET with a bounded retry on transient network failure.
    On a result whose error is in _RETRYABLE_ERRORS ('offline' -- URLError/
    TimeoutError), retry up to `retries` times after `retry_delay` seconds, so a
    single dropped/slow request doesn't strand a tile on 'offline' until its next
    (minutes-away) poll. A 304, any 200, and every deterministic error return on
    the first attempt. Runs on the feed worker thread; the retry sleep is bounded
    and the worker's stop() join tolerates it."""
    result = _fetch_once(url, headers, etag, last_modified, timeout, max_bytes)
    attempt = 0
    while (attempt < retries and result.status == "error"
           and result.error in _RETRYABLE_ERRORS):
        attempt += 1
        if retry_delay > 0:
            time.sleep(retry_delay)
        result = _fetch_once(url, headers, etag, last_modified, timeout, max_bytes)
    return result


def _fetch_once(url, headers=None, etag=None, last_modified=None, timeout=12,
                max_bytes=2_000_000):
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
                               response.headers.get("Last-Modified"), None,
                               _poll_interval(response))
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return FetchResult("not_modified", None, None, etag, last_modified, None)
        return FetchResult("error", None, None, None, None, _error_word(exc))
    except (urllib.error.URLError, TimeoutError) as exc:
        return FetchResult("error", None, None, None, None, _error_word(exc))


def send(url, method, headers=None, timeout=12):
    """Fire a bodyless mutating request (PATCH a thread, PUT /notifications) for
    the mark-as-read actions. Any 2xx -> SendResult('ok', code, None); failures
    map through the same taxonomy as fetch(). TLS uses the default verifying
    context (never weakened); no response body is read."""
    request_headers = {"User-Agent": _DEFAULT_UA}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return SendResult("ok", response.status, None)
    except urllib.error.HTTPError as exc:
        return SendResult("error", exc.code, _error_word(exc))
    except (urllib.error.URLError, TimeoutError) as exc:
        return SendResult("error", None, _error_word(exc))
