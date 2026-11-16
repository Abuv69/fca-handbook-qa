"""Turn raw API or file records into clean Provision objects.

This is the only module that knows what the source data looks like. If the
Handbook API names its fields differently from the guesses in FIELD_MAP, this is
the one place to change.
"""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Iterable

# For each field we need, the keys to look for in a raw record, in order.
# TODO(you): after `python -m fcaqa probe ...`, put the API's real key names first.
FIELD_MAP: dict[str, list[str]] = {
    "provision_id": ["provision_id", "reference", "ref", "provisionReference", "id", "name"],
    "title": ["title", "heading", "sectionTitle"],
    "body": ["body", "text", "content", "html", "provisionText"],
    "provision_type": ["provision_type", "provisionType", "type"],
    "url": ["url", "link", "href"],
}

# 'CONC 5.2A.4R' -> sourcebook CONC, chapter 5, section 5.2A, paragraph 4, type R.
# The letters after the paragraph number are an optional suffix letter (as in 4A)
# followed by the provision type, so '4AR' is paragraph 4A, type R.
_ID_RE = re.compile(
    r"^(?P<book>[A-Z]+)\s+(?P<chapter>\d+[A-Z]?)\.(?P<sec>\d+[A-Z]?)\.(?P<para>\d+)(?P<letters>[A-Z]{0,3})$"
)
_TWO_LETTER_TYPES = ("UK", "EU")


@dataclass(frozen=True)
class Provision:
    provision_id: str
    sourcebook: str
    chapter: str | None
    section: str | None
    provision_type: str | None
    title: str
    body: str
    url: str | None
    content_hash: str


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in {"p", "br", "li", "div", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append(" ")


def clean_text(value: Any) -> str:
    """Strip HTML tags, decode entities and collapse whitespace."""
    if value is None:
        return ""
    text = str(value)
    if "<" in text and ">" in text:
        parser = _TextExtractor()
        parser.feed(text)
        text = "".join(parser.parts)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalise_id(value: str) -> str:
    """One canonical spelling for an ID, so 'conc 5.2a.4 r' equals 'CONC 5.2A.4R'."""
    text = re.sub(r"\s+", " ", str(value)).strip().upper()
    match = re.match(r"^([A-Z]+)\s*(.*)$", text)
    if not match:
        return text
    book, rest = match.group(1), match.group(2).replace(" ", "")
    return f"{book} {rest}".strip()


def split_id(provision_id: str) -> dict[str, str | None]:
    """Work out chapter, section and type from an ID. Unknown shapes return Nones."""
    match = _ID_RE.match(provision_id)
    if not match:
        book = provision_id.split(" ")[0] if provision_id else ""
        return {"sourcebook": book, "chapter": None, "section": None, "provision_type": None}
    letters = match["letters"]
    if letters.endswith(_TWO_LETTER_TYPES):
        ptype = letters[-2:]
    else:
        ptype = letters[-1:] or None
    return {
        "sourcebook": match["book"],
        "chapter": match["chapter"],
        "section": f"{match['chapter']}.{match['sec']}",
        "provision_type": ptype,
    }


def content_hash(title: str, body: str, provision_type: str | None) -> str:
    """Fingerprint of the content. If this changes, the provision changed."""
    joined = "\x1f".join([title, body, provision_type or ""])
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _pick(raw: dict[str, Any], field: str) -> Any:
    for key in FIELD_MAP[field]:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def provision_from_raw(raw: dict[str, Any], sourcebook: str | None = None) -> Provision | None:
    """Build a Provision from one raw record, or None if it has no ID."""
    raw_id = _pick(raw, "provision_id")
    if raw_id is None:
        return None
    provision_id = normalise_id(raw_id)
    parts = split_id(provision_id)
    title = clean_text(_pick(raw, "title"))
    body = clean_text(_pick(raw, "body"))
    ptype = clean_text(_pick(raw, "provision_type")) or parts["provision_type"]
    return Provision(
        provision_id=provision_id,
        sourcebook=(sourcebook or parts["sourcebook"] or "").upper(),
        chapter=parts["chapter"],
        section=parts["section"],
        provision_type=ptype or None,
        title=title,
        body=body,
        url=_pick(raw, "url"),
        content_hash=content_hash(title, body, ptype),
    )


def find_items(payload: Any) -> list[dict[str, Any]]:
    """Find the list of records inside an API response, whatever it is wrapped in."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "results", "data", "provisions", "content", "records"):
            if isinstance(payload.get(key), list):
                return find_items(payload[key])
        lists = [v for v in payload.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        if lists:
            return find_items(max(lists, key=len))
    return []


def parse_records(records: Iterable[dict[str, Any]], sourcebook: str | None = None) -> list[Provision]:
    """Parse many records, skipping any that have no ID."""
    provisions = (provision_from_raw(record, sourcebook) for record in records)
    return [p for p in provisions if p is not None]
