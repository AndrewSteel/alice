"""Title and content part of an image markdown."""
from __future__ import annotations

import posixpath
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PLACE_SEP = " – "  # separates the place in the title; never part of a short title (vision.clean_title)


def time_prefix(taken: str | None, modified, tz: str) -> str:
    """`YYYY-MM-DD hh.mm.ss` of `taken` (camera clock as read, EC-2), else `modified` of the original in
    local time (AK-28)."""
    if isinstance(taken, str) and len(taken) >= 19:
        try:
            return datetime.strptime(taken[:19], "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d %H.%M.%S")
        except ValueError:
            pass
    if isinstance(modified, str) and modified.strip():
        try:
            dt = datetime.fromisoformat(modified.strip().replace("Z", "+00:00"))
        except ValueError:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H.%M.%S")
    return ""


def place_label(location) -> str:
    """`city`, else `country`; empty without a place."""
    if not isinstance(location, dict):
        return ""
    for key in ("city", "country"):
        value = location.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def base_title(prefix: str, short: str) -> str:
    return f"{prefix} {short}".strip() if prefix else short


def with_place(title: str, location) -> str:
    """Title with the place suffix set or replaced (AK-27, AK-29)."""
    base = title.split(PLACE_SEP, 1)[0].rstrip()
    label = place_label(location)
    return f"{base}{PLACE_SEP}{label}" if label else base


def _fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def content(description: str, text_in_image: str, locations: list[dict]) -> str:
    """Description, the section „Text im Bild“ only with readable text (AK-20), links to the original.
    The transcription sits in a code block whose fence is longer than any backtick run in it, so `---`,
    backticks or `#` cannot break the markdown (EC-8)."""
    parts = [description.strip()]
    if text_in_image.strip():
        fence = _fence(text_in_image)
        parts.append(f"## Text im Bild\n\n{fence}text\n{text_in_image.strip(chr(10))}\n{fence}")
    links = []
    for loc in locations or []:
        if isinstance(loc, dict) and loc.get("path"):
            links.append(f"- Original: [{posixpath.basename(loc['path'])}](<{loc['path']}>)")
    if links:
        parts.append("\n".join(links))
    return "\n\n".join(parts) + "\n"
