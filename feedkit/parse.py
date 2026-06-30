"""Pure feed/response parsers: RSS/Atom XML, JSON, plain text, and GitHub
check-runs/notifications. No network, no Tk. Output text is sanitized and
truncated so hostile remote content can't corrupt the canvas or blow out the
layout. parse_rss refuses DOCTYPE/ENTITY payloads (xml.etree is vulnerable to
entity-expansion and there is no stdlib defusedxml)."""
import datetime
import json
import re
import xml.etree.ElementTree as ET

import feedkit.model as model
from feedkit.model import Item, Status, strip_control_chars, truncate

_ATOM = "{http://www.w3.org/2005/Atom}"
_DOCTYPE = re.compile(rb"<!(DOCTYPE|ENTITY)", re.IGNORECASE)
_LINE_MAX = 64


def _local(tag):
    """Local element name with any '{namespace}' prefix stripped."""
    return tag.rsplit("}", 1)[-1]


def _clean(text, n=_LINE_MAX):
    return truncate(strip_control_chars(text or ""), n)


def _child_text(parent, local):
    for child in parent:
        if _local(child.tag) == local:
            return child.text
    return None


def _atom_link(entry):
    """The entry's alternate HTML link href (fall back to the first href present)."""
    fallback = None
    for child in entry:
        if _local(child.tag) != "link":
            continue
        href = child.get("href")
        if not href:
            continue
        if child.get("rel") in (None, "alternate"):
            return href.strip()
        if fallback is None:
            fallback = href.strip()
    return fallback


def parse_rss(body, items):
    if _DOCTYPE.search(body or b""):
        raise ValueError("unsafe XML (DOCTYPE/ENTITY rejected)")
    root = ET.fromstring(body)
    tag = _local(root.tag)
    out = []
    if tag in ("rss", "RDF"):
        # Match items by local-name anywhere under the root: RSS 2.0 nests <item>
        # inside <channel>, but RSS 1.0/RDF makes <item> a direct child of <rdf:RDF>
        # (and namespaces every tag), so a namespace-exact channel/item lookup
        # silently returns nothing. iter() + local-name handles both.
        for node in root.iter():
            if _local(node.tag) != "item":
                continue
            url = _child_text(node, "link")
            out.append(Item(_clean(_child_text(node, "title")), url.strip() if url else None))
            if len(out) >= items:
                break
    elif tag == "feed":
        for entry in root.findall(_ATOM + "entry"):
            out.append(Item(_clean(_child_text(entry, "title")), _atom_link(entry)))
            if len(out) >= items:
                break
    return out


def _walk(data, path):
    node = data
    for seg in path.split("."):
        if isinstance(node, list) and seg.isdigit():
            idx = int(seg)
            node = node[idx] if 0 <= idx < len(node) else None
        elif isinstance(node, dict):
            node = node.get(seg)
        else:
            return None
        if node is None:
            return None
    return node


def parse_json(body, path, fields, items):
    node = _walk(json.loads(body), path)
    if not isinstance(node, list):
        return []
    text_key = fields.get("text")
    url_key = fields.get("url")
    out = []
    for element in node:
        if not isinstance(element, dict):
            continue
        text = element.get(text_key) if text_key else None
        url = element.get(url_key) if url_key else None
        out.append(Item(_clean("" if text is None else str(text)),
                        url if isinstance(url, str) and url else None))
        if len(out) >= items:
            break
    return out


def _decode(body, content_type):
    charset = "utf-8"
    if content_type and "charset=" in content_type.lower():
        charset = content_type.lower().split("charset=", 1)[1].split(";")[0].strip().strip("\"'") or "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def parse_text(body, content_type, regex, items, url=None):
    text = _decode(body, content_type)
    if regex:
        match = re.search(regex, text)
        if not match:
            return [Item(_clean("(no match)"), url)]
        value = match.group(1) if match.groups() else match.group(0)
        return [Item(_clean(value), url)]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return [Item(_clean(ln), url) for ln in lines[:items]]


_GOOD_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})
_CI_WORD = {"success": "passing", "failure": "failing", "pending": "pending", "none": "—"}


def parse_check_runs(body):
    """Reduce a check-runs response to one of none/pending/success/failure, per
    the spec's order: empty -> none; ANY run not completed -> pending (a re-run
    in progress shows amber even if a sibling already failed); all completed ->
    success iff every conclusion is success/neutral/skipped, else failure."""
    data = json.loads(body)
    runs = data.get("check_runs") if isinstance(data, dict) else None
    if not runs:
        return "none"
    if any(run.get("status") != "completed" for run in runs):
        return "pending"
    if all(run.get("conclusion") in _GOOD_CONCLUSIONS for run in runs):
        return "success"
    return "failure"


def parse_notifications(body):
    """Count unread notification threads (the endpoint returns unread-only by
    default; we still filter unread != false defensively)."""
    data = json.loads(body)
    if not isinstance(data, list):
        return 0
    return sum(1 for n in data if isinstance(n, dict) and n.get("unread", True))


def _parse_ts(s):
    """ISO-8601 timestamp (e.g. '2026-06-29T00:00:00Z') -> float unix seconds.
    Returns 0.0 for None/missing/unparseable values (the HUD renders no age)."""
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, AttributeError):
        return 0.0


def parse_notification_items(body, max_items):
    """Parse a /notifications response into (list[NotifItem], total_unread).
    total counts every unread thread on the page (drives the badge); the list is
    capped at max_items. Defensive against null subject.url and missing keys."""
    data = json.loads(body)
    if not isinstance(data, list):
        return [], 0
    unread = [n for n in data if isinstance(n, dict) and n.get("unread", True)]
    total = len(unread)
    out = []
    for n in unread[:max_items]:
        subj = n.get("subject") or {}
        stype = subj.get("type") or ""
        repo = (n.get("repository") or {}).get("full_name") or ""
        suburl = subj.get("url") or ""              # JSON null -> "" (NOT .get(k,"") -> None)
        seg = suburl.rsplit("/", 1)[-1] if suburl else ""
        number = "#" + seg if seg.isdigit() else ""
        reason = n.get("reason") or ""
        out.append(model.NotifItem(
            glyph=model.glyph_for(stype),
            repo=repo,
            number=number,
            reason_label=model.reason_label(reason),
            urgency=model.urgency_for(reason),
            updated_at=_parse_ts(n.get("updated_at")),
            title=_clean(subj.get("title") or ""),
            url=model.notification_url(stype, subj.get("url"), repo),
        ))
    return out, total


def compose_github_status(repo, branch, ci_state, notif_count, ci_shown=True):
    """Build the github tile's header Status. When CI is shown the text leads with
    the colored ● + CI word and the click target is the repo's Actions page; a
    notifications-only tile shows just the name and points at /notifications."""
    name = repo.split("/")[-1]
    if ci_shown:
        text = "%s ● %s" % (name, _CI_WORD.get(ci_state, "—"))
        url = "https://github.com/%s/actions" % repo
    else:
        text = name
        url = "https://github.com/notifications"
    if notif_count is not None:
        text += "  \U0001f514 %s" % ("50+" if notif_count >= 50 else notif_count)
    return Status(_clean(text, 40), ci_state, url)
