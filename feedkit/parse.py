"""Pure feed/response parsers: RSS/Atom XML, JSON, plain text, and GitHub
check-runs/notifications. No network, no Tk. Output text is sanitized and
truncated so hostile remote content can't corrupt the canvas or blow out the
layout. parse_rss refuses DOCTYPE/ENTITY payloads (xml.etree is vulnerable to
entity-expansion and there is no stdlib defusedxml)."""
import json
import re
import xml.etree.ElementTree as ET

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
