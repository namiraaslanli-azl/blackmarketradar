"""Deduplication: one finding per entity, last_seen moves, statuses never go backwards."""

import csv
import io
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from radar.importers.common import map_status
from radar.importers.seed_csv import import_rows
from radar.models import Finding, FindingEvent
from radar.store import FindingIn, merge_status, upsert_finding

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def count(session, *where):
    return session.scalar(select(func.count()).select_from(Finding).where(*where))


def test_redetection_updates_last_seen_only_once(session):
    a = upsert_finding(session, FindingIn(url="https://www.azmostbet90.com/", seen_at=T0, matched_keywords=["mostbet"]))
    b = upsert_finding(session, FindingIn(url="azmostbet90.com/az?utm_source=x", seen_at=T0 + timedelta(days=3),
                                          matched_keywords=["bonus"], views=10))
    c = upsert_finding(session, FindingIn(url="http://AZMOSTBET90.com", seen_at=T0 - timedelta(days=2)))
    assert a.created and not b.created and not c.created
    assert a.finding.id == b.finding.id == c.finding.id
    assert count(session) == 1
    f = a.finding
    assert f.first_seen == T0 - timedelta(days=2)
    assert f.last_seen == T0 + timedelta(days=3)
    assert f.matched_keywords == ["mostbet", "bonus"]
    assert f.views == 10
    kinds = session.scalars(select(FindingEvent.kind).where(FindingEvent.finding_id == f.id)).all()
    assert kinds.count("detected") == 1 and kinds.count("redetected") == 2


def test_status_merge_never_regresses(session):
    upsert_finding(session, FindingIn(url="https://pinco08v.com", status="blocked"))
    r = upsert_finding(session, FindingIn(url="https://www.pinco08v.com/", status="confirmed"))
    assert r.finding.status == "blocked"
    r = upsert_finding(session, FindingIn(url="https://pinco08v.com", status="new"), status_policy="keep")
    assert r.finding.status == "blocked"
    assert merge_status("new", "reported") == "reported"
    assert merge_status("false_positive", "new") == "new"


def test_keep_policy_preserves_human_label(session):
    upsert_finding(session, FindingIn(url="https://example-news.az/casino", status="false_positive"))
    r = upsert_finding(session, FindingIn(url="https://example-news.az/", status="confirmed"), status_policy="keep")
    assert r.finding.status == "false_positive"


def test_metrics_take_max_and_fill_empty_fields(session):
    upsert_finding(session, FindingIn(url="https://t.me/melbetkassa", subscribers=1200))
    r = upsert_finding(session, FindingIn(url="https://t.me/MelbetKassa", subscribers=900, title="Kassa"))
    assert r.finding.subscribers == 1200
    assert r.finding.title == "Kassa"


def test_status_mapping():
    assert map_status("Aktiv") == ("confirmed", True)
    assert map_status("Passiv") == ("confirmed", False)
    assert map_status("Bloklanıb") == ("blocked", False)
    assert map_status("Şikayət olunub") == ("reported", None)
    assert map_status("Yoxlanılmayıb") == ("new", None)
    assert map_status("", "Şikayət olunub") == ("reported", None)
    assert map_status("Bloklanıb", "Şikayət olunub") == ("blocked", False)
    assert map_status("") == ("confirmed", None)


def _rows(*dicts):
    cols = ["finding_id", "url", "source_sheets", "source_rows", "original_status", "status", "tags", "raw_json"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols + ["landing_url", "entity_type"])
    w.writeheader()
    for d in dicts:
        w.writerow({"raw_json": json.dumps(d.get("raw", {})), **{k: v for k, v in d.items() if k != "raw"}})
    return list(csv.DictReader(io.StringIO(buf.getvalue())))


def test_import_dedupes_across_sheets_by_host(session):
    rows = _rows(
        {"finding_id": "F1", "url": "https://aze.1xbet.com", "source_sheets": "Organic Domain", "source_rows": "10"},
        {"finding_id": "F2", "url": "aze.1xbet.com/", "source_sheets": "Kohne Tapintilar", "source_rows": "442",
         "original_status": "Passiv"},
        {"finding_id": "F3", "url": "/https://www.AZE.1xbet.com/az", "source_sheets": "Kohne Tapintilar",
         "source_rows": "449", "original_status": "Bloklanıb"},
        {"finding_id": "F4", "url": "URL", "source_sheets": "Kohne Tapintilar", "source_rows": "1"},
    )
    batch = import_rows(session, rows, kind="test", filename="t.csv", sha256="0" * 64)
    assert batch.report["created"] == 1
    assert batch.report["duplicates_in_file"] == 2
    assert len(batch.report["skipped_invalid_url"]) == 1
    f = session.scalar(select(Finding))
    assert f.canonical_key == "domain:aze.1xbet.com"
    assert f.status == "blocked"
    assert "historical" in f.tags
    assert f.public_id == "F1"
    assert len(f.raw["sources"]) == 3


def test_reimport_is_idempotent(session):
    rows = _rows({"finding_id": "F9", "url": "https://misli-az.com", "source_sheets": "Kohne Tapintilar",
                  "source_rows": "5", "original_status": "Aktiv"})
    import_rows(session, rows, kind="test", filename="t.csv", sha256="0" * 64)
    b2 = import_rows(session, rows, kind="test", filename="t.csv", sha256="0" * 64)
    assert b2.report["created"] == 0 and b2.report["merged_into_existing"] == 1
    assert count(session) == 1
    assert len(session.scalar(select(Finding)).raw["sources"]) == 1


def test_parse_int_counts():
    from radar.importers.common import parse_int

    assert parse_int("1677") == 1677
    assert parse_int("1 677") == 1677
    assert parse_int("1.2k") == 1200
    assert parse_int("1,5M") == 1_500_000
    assert parse_int("12 min") == 12_000
    assert parse_int("n/a") is None


def test_seed_xlsx_matches_csv_import(session, tmp_path):
    from openpyxl import Workbook

    from radar.importers.seed_csv import import_seed_csv

    header = ["finding_id", "url", "source_sheets", "source_rows", "original_status", "status", "tags", "raw_json"]
    wb = Workbook()
    wb.active.title = "Xülasə"
    ws = wb.create_sheet("Findings")
    ws.append(header)
    ws.append(["F1", "https://aze.1xbet.com", "Organic Domain", "10", None, "confirmed", None, "{}"])
    ws.append(["F2", "/https://www.aze.1xbet.com/", "Kohne Tapintilar", "442", "Bloklanıb", "blocked", "historical", "{}"])
    ws.append([None] * len(header))
    p = tmp_path / "Qara_Bazar_Import_Seed.xlsx"
    wb.save(p)
    batch = import_seed_csv(session, p)
    assert batch.kind == "seed_xlsx"
    assert batch.report["rows_read"] == 2 and batch.report["created"] == 1
    assert session.scalar(select(Finding)).status == "blocked"
