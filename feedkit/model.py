"""Pure feed helpers: data types, text sanitizing, conditional-request headers,
and GitHub URL/header builders. No network, no Tk, no clock -- the worker injects
``now`` and raw bytes. Everything here is deterministic and unit-testable."""
from collections import namedtuple
import math
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


_VALID_TYPES = ("rss", "json", "text", "github")
_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def _coerce_int(value, default, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    # Guard against non-finite floats (NaN, Inf) which int() cannot convert
    if isinstance(value, float) and not math.isfinite(value):
        return default
    return max(lo, min(hi, int(value)))


def _title_from_url(url):
    try:
        return urllib.parse.urlparse(url).netloc or "feed"
    except ValueError:
        return "feed"


def normalize_feed(raw):
    """Validate/coerce one feed dict from config. Never raises. Returns a dict
    with valid/error plus the type-specific keys; invalid feeds keep a title so
    the HUD can still render an error tile."""
    if not isinstance(raw, dict):
        return {"type": "?", "title": "feed", "items": 3, "interval": 600,
                "valid": False, "error": "not an object"}
    ftype = raw.get("type")
    title = raw.get("title")
    title = title.strip() if isinstance(title, str) and title.strip() else None
    out = {"type": ftype, "title": title, "valid": True, "error": None}

    if ftype not in _VALID_TYPES:
        out.update(valid=False, error="unknown type %r" % (ftype,),
                   title=title or "feed", items=3, interval=600)
        return out

    floor = 120 if ftype == "github" else 300
    out["interval"] = _coerce_int(raw.get("interval"), floor, floor, 86400)

    if ftype in ("rss", "json", "text"):
        out["items"] = _coerce_int(raw.get("items"), 3, 1, 10)
        url = raw.get("url")
        if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
            out.update(valid=False, error="missing/invalid url", title=title or "feed")
            return out
        out["url"] = url
        out["title"] = title or _title_from_url(url)
        if ftype == "json":
            path = raw.get("path")
            fields = raw.get("fields")
            if not isinstance(path, str) or not path:
                out.update(valid=False, error="json feed needs 'path'")
                return out
            if not isinstance(fields, dict) or not isinstance(fields.get("text"), str):
                out.update(valid=False, error="json feed needs fields.text")
                return out
            out["path"] = path
            out["fields"] = {"text": fields.get("text"),
                             "url": fields.get("url") if isinstance(fields.get("url"), str) else None}
        elif ftype == "text":
            rgx = raw.get("regex")
            out["regex"] = rgx if isinstance(rgx, str) and rgx else None
        return out

    # github
    repo = raw.get("repo")
    if not isinstance(repo, str) or not _REPO_RE.match(repo):
        out.update(valid=False, error="github feed needs repo 'owner/name'",
                   title=title or "github")
        return out
    out["repo"] = repo
    branch = raw.get("branch")
    out["branch"] = branch if isinstance(branch, str) and branch else "main"
    show = raw.get("show")
    show = [s for s in show if s in ("ci", "notifications")] if isinstance(show, list) else []
    if not show:
        show = ["ci", "notifications"] if not isinstance(raw.get("show"), list) else None
    if not show:
        out.update(valid=False, error="github 'show' must include ci or notifications",
                   title=title or "github")
        return out
    out["show"] = show
    out["title"] = title or repo.split("/")[-1]
    return out


def due_feeds(feeds, last_fetch, now, stagger=2.0):
    """Indices of valid feeds whose interval has elapsed. ``now`` and the
    ``last_fetch`` values are seconds since the manager started (monotonic). The
    first fetch of feed i is staggered to ``i * stagger`` seconds so they don't
    all fire on the same tick."""
    due = []
    for i, feed in enumerate(feeds):
        if not feed.get("valid"):
            continue
        last = last_fetch.get(i)
        if last is None:
            if now >= i * stagger:
                due.append(i)
        elif now - last >= feed["interval"]:
            due.append(i)
    return due
