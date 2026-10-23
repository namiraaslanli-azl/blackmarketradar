"""Shared mapping from the analyst workbook vocabulary to platform fields."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from dateutil import parser as dateparser

# Workbook "Status" values → platform status. "Passiv" means the site/channel no longer
# works but the finding itself was confirmed; liveness is kept separately in is_live.
STATUS_MAP = {
    "aktiv": ("confirmed", True),
    "passiv": ("confirmed", False),
    "bloklanıb": ("blocked", False),
    "bloklanib": ("blocked", False),
    "şikayət olunub": ("reported", None),
    "sikayet olunub": ("reported", None),
    "yoxlanılmayıb": ("new", None),
    "yoxlanilmayib": ("new", None),
}


def map_status(original: str | None, complaint: str | None = None, default: str = "confirmed") -> tuple[str, bool | None]:
    """Return (status, is_live). Unknown or empty original → (default, None)."""
    key = (original or "").strip().lower()
    status, live = STATUS_MAP.get(key, (default if not key else "new", None))
    if (complaint or "").strip().lower() in ("şikayət olunub", "sikayet olunub") and status in ("new", "confirmed"):
        status = "reported"
    return status, live


def parse_bool_az(value) -> bool | None:
    v = str(value or "").strip().lower()
    if v in ("bəli", "beli", "yes", "true", "1", "hə", "he"):
        return True
    if v in ("xeyr", "no", "false", "0", "yox"):
        return False
    return None


def parse_int(value) -> int | None:
    """'1677', '1 677', '1,2k', '1.2K', '3M', '15 min' (Azerbaijani "min" = thousand) → int."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().replace("\u00a0", "").replace(" ", "")
    m = re.match(r"^(\d+(?:[.,]\d+)?)(k|K|m|M|min|mln|млн|тыс|к|К)?$", s)
    if m and m.group(2):
        mult = {"k": 1_000, "min": 1_000, "тыс": 1_000, "к": 1_000, "m": 1_000_000, "mln": 1_000_000,
                "млн": 1_000_000}[m.group(2).lower()]
        return int(float(m.group(1).replace(",", ".")) * mult)
    digits = re.sub(r"[.,]", "", s)
    return int(digits) if digits.isdigit() else None


def parse_date(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) and value > 10**9:
        return datetime.fromtimestamp(value / (1000 if value > 10**11 else 1), tz=timezone.utc)
    try:
        d = dateparser.parse(str(value), dayfirst=True)
    except (ValueError, OverflowError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def split_list(value: str | None) -> list[str]:
    return [p.strip() for p in re.split(r"[,;|]", value or "") if p.strip()]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
