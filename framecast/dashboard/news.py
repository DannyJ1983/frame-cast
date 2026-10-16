"""Headlines from an RSS or Atom feed; BBC News by default."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

BBC = "https://feeds.bbci.co.uk/news/{}rss.xml"
# Feed choices on the phone page: key -> (name shown, address).
NEWS_FEEDS: dict[str, tuple[str, str]] = {
    "bbc-top": ("BBC News: top stories", BBC.format("")),
    "bbc-uk": ("BBC News: UK", BBC.format("uk/")),
    "bbc-world": ("BBC News: world", BBC.format("world/")),
    "bbc-england": ("BBC News: England", BBC.format("england/")),
    "bbc-scotland": ("BBC News: Scotland", BBC.format("scotland/")),
    "bbc-wales": ("BBC News: Wales", BBC.format("wales/")),
    "bbc-ni": ("BBC News: Northern Ireland", BBC.format("northern_ireland/")),
    "bbc-business": ("BBC News: business", BBC.format("business/")),
    "bbc-technology": ("BBC News: technology", BBC.format("technology/")),
    "bbc-science": ("BBC News: science", BBC.format("science_and_environment/")),
    "bbc-entertainment": ("BBC News: entertainment", BBC.format("entertainment_and_arts/")),
    "guardian-uk": ("The Guardian", "https://www.theguardian.com/uk/rss"),
    "sky": ("Sky News", "https://feeds.skynews.com/feeds/rss/home.xml"),
}
DEFAULT_FEED = "bbc-top"
MAX_HEADLINES = 8
_ATOM = "{http://www.w3.org/2005/Atom}"
_TAGS = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", text or "")).split())


def _when(text: str | None) -> str | None:
    """An RSS or Atom date as an ISO time in UTC, or None."""
    if not text:
        return None
    try:
        moment = parsedate_to_datetime(text.strip())
    except (TypeError, ValueError):
        try:
            moment = datetime.fromisoformat(text.strip())
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_feed(text: str, limit: int = MAX_HEADLINES) -> dict[str, Any]:
    """Read the feed's name and its first headlines. Raises ValueError if it isn't RSS or Atom."""
    try:
        root = ET.fromstring(text.lstrip("\ufeff").strip())
    except ET.ParseError as err:
        raise ValueError(f"not a feed: {err}") from err
    if root.tag == f"{_ATOM}feed":
        source = _clean(root.findtext(f"{_ATOM}title"))
        entries = [
            (e.findtext(f"{_ATOM}title"), e.findtext(f"{_ATOM}published") or e.findtext(f"{_ATOM}updated"))
            for e in root.iter(f"{_ATOM}entry")
        ]
    elif root.find("channel") is not None:
        channel = root.find("channel")
        assert channel is not None
        source = _clean(channel.findtext("title"))
        entries = [(i.findtext("title"), i.findtext("pubDate")) for i in channel.iter("item")]
    else:
        raise ValueError("not an RSS or Atom feed")
    headlines: list[dict[str, Any]] = []
    seen: set[str] = set()
    for title, published in entries:
        clean = _clean(title)
        if not clean or clean.lower() in seen:
            continue
        seen.add(clean.lower())
        headlines.append({"title": clean, "published": _when(published)})
        if len(headlines) >= limit:
            break
    return {"source": source, "headlines": headlines}
