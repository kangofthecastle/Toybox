"""Pure feed/response parsers: RSS/Atom XML, JSON, plain text, and GitHub
check-runs/notifications. No network, no Tk. Output text is sanitized and
truncated so hostile remote content can't corrupt the canvas or blow out the
layout. parse_rss refuses DOCTYPE/ENTITY payloads (xml.etree is vulnerable to
entity-expansion and there is no stdlib defusedxml)."""
import datetime
import json
import math
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
            thread_url=n.get("url") or "",
        ))
    return out, total


_SEARCH_REPO_PREFIX = "https://api.github.com/repos/"


def parse_search_items(body, max_items):
    """Parse a /search/issues response into (list[NotifItem], total_count).
    total_count drives the count shown in the tile title; the list is capped at
    max_items. Defensive against missing keys and non-list items. A result with
    a 'pull_request' object is a PR (⇄); otherwise an issue (◉)."""
    data = json.loads(body)
    items_raw = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items_raw, list):
        return [], 0
    total = data.get("total_count")
    if not isinstance(total, int) or isinstance(total, bool):
        total = len(items_raw)
    out = []
    for it in items_raw[:max_items]:
        if not isinstance(it, dict):
            continue
        is_pr = isinstance(it.get("pull_request"), dict)
        repo_url = it.get("repository_url") or ""
        repo = (repo_url[len(_SEARCH_REPO_PREFIX):]
                if isinstance(repo_url, str) and repo_url.startswith(_SEARCH_REPO_PREFIX)
                else "")
        num = it.get("number")
        number = "#%d" % num if isinstance(num, int) and not isinstance(num, bool) else ""
        user = it.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        label = ("@" + login) if login else ""
        urgency = "low" if (is_pr and it.get("draft")) else "normal"
        html = it.get("html_url")
        out.append(model.NotifItem(
            glyph=model.glyph_for("PullRequest" if is_pr else "Issue"),
            repo=repo,
            number=number,
            reason_label=label,
            urgency=urgency,
            updated_at=_parse_ts(it.get("updated_at")),
            title=_clean(it.get("title") or ""),
            url=html if model.is_web_url(html) else "",
        ))
    return out, total


def _finite_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def parse_stock_chart(body, symbol):
    """Parse a Yahoo v8 chart response into a Quote, or None. NEVER raises
    (defensive over untrusted bytes). Price prefers meta.regularMarketPrice and
    falls back to the last finite close; change_pct is the day's move vs
    chartPreviousClose (then previousClose), 0.0 when that is missing/zero;
    series is the finite close list."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    try:
        chart = data.get("chart") if isinstance(data, dict) else None
        results = chart.get("result") if isinstance(chart, dict) else None
        if not results:
            return None
        result = results[0]
        if not isinstance(result, dict):
            return None
        meta = result.get("meta")
        meta = meta if isinstance(meta, dict) else {}
        series = []
        indicators = result.get("indicators")
        if isinstance(indicators, dict):
            qlist = indicators.get("quote")
            if isinstance(qlist, list) and qlist and isinstance(qlist[0], dict):
                closes = qlist[0].get("close")
                if isinstance(closes, list):
                    series = [float(c) for c in closes if _finite_num(c)]
        price = meta.get("regularMarketPrice")
        if not _finite_num(price):
            price = series[-1] if series else None
        if not _finite_num(price):
            return None
        price = float(price)
        prev = meta.get("chartPreviousClose")
        if not _finite_num(prev):
            prev = meta.get("previousClose")
        if _finite_num(prev) and float(prev) != 0.0:
            change_pct = (price - float(prev)) / float(prev) * 100.0
        else:
            change_pct = 0.0
        return model.Quote(symbol, price, change_pct, series)
    except Exception:
        return None


def parse_geocode(body):
    """Parse an Open-Meteo geocoding response into (lat, lon, name), or None.
    NEVER raises. Takes the first result; requires finite lat/lon; name defaults
    to "" when missing."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    try:
        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            return None
        r = results[0]
        if not isinstance(r, dict):
            return None
        lat, lon = r.get("latitude"), r.get("longitude")
        if not _finite_num(lat) or not _finite_num(lon):
            return None
        name = r.get("name")
        name = name if isinstance(name, str) and name else ""
        return (float(lat), float(lon), name)
    except Exception:
        return None


def parse_weather(body, range_):
    """Parse an Open-Meteo forecast response into a model.Weather, or None. NEVER
    raises. 'today' -> hourly series + today's daily max/min; '3d'/'7d' -> daily-max
    series + max(daily max)/min(daily min). Non-finite series values are dropped.
    Returns None only when the current temperature is missing/unparseable."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        cur = data.get("current")
        cur = cur if isinstance(cur, dict) else {}
        current = cur.get("temperature_2m")
        if not _finite_num(current):
            return None
        units_map = data.get("current_units")
        unit = ""
        if isinstance(units_map, dict) and isinstance(units_map.get("temperature_2m"), str):
            unit = units_map.get("temperature_2m")
        daily = data.get("daily")
        daily = daily if isinstance(daily, dict) else {}
        dmax = [float(v) for v in (daily.get("temperature_2m_max") or []) if _finite_num(v)]
        dmin = [float(v) for v in (daily.get("temperature_2m_min") or []) if _finite_num(v)]
        if range_ == "today":
            hourly = data.get("hourly")
            hourly = hourly if isinstance(hourly, dict) else {}
            series = [float(v) for v in (hourly.get("temperature_2m") or []) if _finite_num(v)]
            hi = dmax[0] if dmax else (max(series) if series else current)
            lo = dmin[0] if dmin else (min(series) if series else current)
        else:
            series = dmax
            hi = max(dmax) if dmax else current
            lo = min(dmin) if dmin else current
        code = int(cur.get("weather_code")) if _finite_num(cur.get("weather_code")) else -1
        feels = cur.get("apparent_temperature")
        feels = float(feels) if _finite_num(feels) else None
        humidity = cur.get("relative_humidity_2m")
        humidity = int(round(float(humidity))) if _finite_num(humidity) else None
        wind = cur.get("wind_speed_10m")
        wind = float(wind) if _finite_num(wind) else None
        precip = None
        for v in (daily.get("precipitation_probability_max") or []):
            if _finite_num(v):
                precip = int(round(float(v)))
                break
        return model.Weather(float(current), float(hi), float(lo), series, unit,
                             code, feels, humidity, wind, precip)
    except Exception:
        return None


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
