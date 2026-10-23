"""Import the original weekly workbook ("Qara Bazar Monitorinq Hesabatı – Weekly").

Each sheet is converted to the seed-row format and passed to `import_rows`, which applies
the shared mapping, deduplication and data-quality report.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from radar.importers.common import file_sha256
from radar.importers.seed_csv import import_rows
from radar.models import ImportBatch
from radar.normalize import clean_raw_url, is_valid_url

# sheet → (url columns in priority order, field map)
SHEETS: dict[str, dict] = {
    "Organic Domain": {"url": ["Domen / URL", "Domen", "URL", "Link"]},
    "Kohne Tapintilar": {"url": ["Saytlar", "Domen / URL", "Link", "URL"]},
    "App store": {"url": ["Link", "Domen / URL", "URL"]},
    "Meta Ads": {"url": ["Reklam linki", "Link"]},
    "Telegram": {"url": ["Link"]},
    "Tiktok Organic": {"url": ["URL", "Link"]},
    "SM Organic": {"url": ["Link", "URL"]},
    "Playstore": {"url": ["Link", "URL"]},
}
FIELD_MAP = {
    "Kateqoriya": "category",
    "Hosting / Registrator": "hosting_registrar",
    "Cloudflare?": "cloudflare",
    "Abuse Email": "abuse_email",
    "Təklif Olunan Təsir Mexanizmi": "suggested_action",
    "Reklamçı": "advertiser",
    "Başlama tarixi": "start_date",
    "Mətn (qısa)": "text",
    "Mətn": "text",
    "Şikayət statusu": "complaint_status",
    "Status": "original_status",
    "Ad": "name",
    "Abunəçi / üzv": "subscribers",
    "Dil / geo": "language_geo",
    "Əsas məlumat və əlaqələr": "text",
    "Mənbə": "source_note",
    "Sorğu": "query",
    "Hesab": "handle",
}
_KNOWN_HEADERS = {h for spec in SHEETS.values() for h in spec["url"]} | set(FIELD_MAP)


def _cell(v):
    if isinstance(v, (datetime, date)):
        return v.strftime("%d.%m.%Y")
    if v is None:
        return ""
    return str(v).strip()


def _header_row(rows: list[tuple]) -> int:
    best, best_hits = 0, -1
    for i, r in enumerate(rows[:10]):
        hits = sum(1 for c in r if _cell(c) in _KNOWN_HEADERS)
        if hits > best_hits:
            best, best_hits = i, hits
    return best


def telegram_url(username: str, link: str) -> tuple[str, str | None]:
    """Rebuild Telegram links broken by Excel. Returns (url, fix applied)."""
    u = (username or "").strip()
    if u.startswith("=+"):
        return f"https://t.me/+{u[2:]}", "fixed_excel_formula_username"
    if link and is_valid_url(link):
        return link, None
    if u.startswith("+"):
        return f"https://t.me/{u}", "link_rebuilt_from_username"
    if re.fullmatch(r"@?[A-Za-z][\w]{3,}", u):
        return f"https://t.me/{u.lstrip('@')}", "link_rebuilt_from_username"
    return link, None


def sheet_rows(sheet_name: str, ws) -> list[dict]:
    spec = SHEETS[sheet_name]
    values = list(ws.iter_rows(values_only=True))
    if not values:
        return []
    h = _header_row(values)
    headers = [_cell(c) for c in values[h]]
    out = []
    for offset, r in enumerate(values[h + 1:], start=h + 2):
        rec = {headers[i]: _cell(c) for i, c in enumerate(r) if i < len(headers) and headers[i] and _cell(c)}
        if not rec:
            continue
        url = next((rec[c] for c in spec["url"] if rec.get(c)), "")
        row: dict = {"source_sheets": sheet_name, "source_rows": str(offset), "raw_json": json.dumps(rec, ensure_ascii=False)}
        fixes = []
        if sheet_name == "Telegram":
            url, fix = telegram_url(rec.get("İstifadəçi adı", ""), rec.get("Link", ""))
            if fix:
                fixes.append(fix)
            row["handle"] = rec.get("İstifadəçi adı", "").lstrip("=")
            kind = rec.get("Növ", "").lower()
            row["entity_type"] = ("telegram_bot" if "bot" in kind else
                                  "telegram_group" if "qrup" in kind or "group" in kind else "telegram_channel")
            row["needs_review"] = "yes" if rec.get("Status", "") in ("", "Yoxlanılmayıb") else "no"
            if row["needs_review"] == "yes":
                row["review_reasons"] = "telegram_unverified"
        if sheet_name == "Tiktok Organic":
            m = re.match(r"^(\S+)\s*\((.+)\)$", rec.get("User / Channel", ""))
            if m:
                row["handle"], row["name"] = m.group(1), m.group(2)
            else:
                row["handle"] = rec.get("User / Channel", "")
        if sheet_name == "App store":
            row["entity_type"] = "app_landing_page"
            row["tags"] = "app_landing"
            row["needs_review"] = "yes"
            row["review_reasons"] = "moved_from_app_store_sheet"
        if sheet_name == "Meta Ads":
            landing = rec.get("Landing", "")
            row["landing_url"] = clean_raw_url(landing) if is_valid_url(landing) else ""
        if sheet_name == "Kohne Tapintilar":
            row["tags"] = "historical"
        if sheet_name == "Playstore" and rec.get("Status", "") in ("", "Yoxlanılmayıb"):
            row["needs_review"], row["review_reasons"] = "yes", "play_store_unverified"
        for col, field in FIELD_MAP.items():
            if rec.get(col) and not row.get(field):
                row[field] = rec[col]
        # Organic Domain rows carry no Status column: they are confirmed findings
        row["status"] = "confirmed" if not row.get("original_status") else ""
        row["url"] = url
        row["data_fixes"] = ", ".join(fixes)
        out.append(row)
    return out


def import_workbook(session: Session, path: Path, seen_at: datetime | None = None) -> ImportBatch:
    wb = load_workbook(path, read_only=True, data_only=False)
    rows: list[dict] = []
    for name in wb.sheetnames:
        match = next((s for s in SHEETS if s.lower() == name.strip().lower()), None)
        if match:
            rows.extend(sheet_rows(match, wb[name]))
    return import_rows(session, rows, kind="workbook", filename=path.name, sha256=file_sha256(path), seen_at=seen_at)
