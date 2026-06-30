"""Pure feed helpers: data types, text sanitizing, conditional-request headers,
and GitHub URL/header builders. No network, no Tk, no clock -- the worker injects
``now`` and raw bytes. Everything here is deterministic and unit-testable."""
from collections import namedtuple
import re
import urllib.parse

Item = namedtuple("Item", ["text", "url"])            # url may be None
Status = namedtuple("Status", ["text", "state", "url"])  # state: success/failure/pending/none

# C0 (except the whitespace we normalize), DEL, and C1 control ranges.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_WS = re.compile(r"\s+")


def strip_control_chars(s):
    """Drop control characters and collapse all whitespace runs to single spaces."""
    if not s:
        return ""
    return _WS.sub(" ", _CONTROL.sub("", s)).strip()


def truncate(s, n):
    """Truncate to at most ``n`` characters, marking elision with a trailing ellipsis."""
    s = s or ""
    if len(s) <= n:
        return s
    if n <= 1:
        return "…"
    return s[:n - 1].rstrip() + "…"


def build_conditional_headers(etag, last_modified):
    """If-None-Match / If-Modified-Since headers for a conditional GET (echo weak
    validators verbatim). Empty dict when neither validator is cached."""
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers


def is_web_url(url):
    """True only for http/https URLs. The single gate on what may be opened in a
    browser -- feed item URLs are attacker-controlled, so file://, javascript:,
    data:, and custom schemes must never reach webbrowser.open."""
    return isinstance(url, str) and url.lower().startswith(("http://", "https://"))


GITHUB_API = "https://api.github.com"


def github_ci_url(repo, branch):
    """check-runs endpoint for repo@branch (covers GitHub Actions; the legacy
    /status endpoint does not). The branch resolves to HEAD server-side; a '/' in
    the ref is percent-encoded."""
    return "%s/repos/%s/commits/%s/check-runs?per_page=100" % (
        GITHUB_API, repo, urllib.parse.quote(branch, safe=""))


def github_notifications_url():
    # per_page=50 so the unread count can actually reach the "50+" render threshold
    # (the API default page size is 30).
    return "%s/notifications?per_page=50" % GITHUB_API


def github_headers(token):
    """Mandatory GitHub REST headers. User-Agent is required (urllib's default UA
    gets a 403). Authorization is added only when a token is present."""
    headers = {
        "User-Agent": "Toybox-WebFeed/1.0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers
