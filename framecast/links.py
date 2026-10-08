"""Pull a web address out of whatever a phone's share menu sends."""

from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING = ".,;:!?'\""
_PAIRS = {")": "(", "]": "[", "}": "{"}


def extract_url(text: str) -> str | None:
    """Return the first http(s) address in ``text``, or None if there isn't one.

    Share menus often send "Page title https://example.com/page" rather than a
    bare address, and people paste links with a full stop on the end.
    """
    match = _URL_RE.search(text or "")
    if not match:
        return None
    url = match.group(0)
    while url:
        last = url[-1]
        if last in _TRAILING:
            url = url[:-1]
        elif last in _PAIRS and url.count(last) > url.count(_PAIRS[last]):
            url = url[:-1]
        else:
            break
    return url or None
