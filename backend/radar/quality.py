"""Data-quality report: what the import produced and what still needs a human."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.models import Finding, ImportBatch, Link


def quality_report(session: Session) -> dict:
    def count(*where):
        return session.scalar(select(func.count()).select_from(Finding).where(*where)) or 0

    domains = Finding.source == "organic_domain"
    by_source = dict(session.execute(select(Finding.source, func.count()).group_by(Finding.source)).all())
    by_status = dict(session.execute(select(Finding.status, func.count()).group_by(Finding.status)).all())
    reasons = dict(session.execute(
        select(func.unnest(Finding.review_reasons).label("r"), func.count()).where(Finding.needs_review)
        .group_by("r").order_by(func.count().desc())
    ).all())
    links = dict(session.execute(select(Link.link_type, func.count()).group_by(Link.link_type)).all())
    return {
        "total_findings": count(),
        "by_source": by_source,
        "by_status": by_status,
        "domains": {
            "total": count(domains),
            "manual_enrichment_from_workbook": count(domains, Finding.enrichment.has_key("manual")),
            "network_enriched": count(domains, Finding.enriched_at.is_not(None)),
            "awaiting_network_enrichment": count(domains, Finding.enriched_at.is_(None)),
            "with_operator": count(domains, Finding.operator_id.is_not(None)),
            "category_from_workbook": count(domains, Finding.category.is_not(None), Finding.category_suggested.is_(False)),
            "category_suggested": count(domains, Finding.category_suggested),
            "impersonation": count(Finding.is_impersonation),
        },
        "with_operator": count(Finding.operator_id.is_not(None)),
        "needs_review": count(Finding.needs_review),
        "needs_review_reasons": reasons,
        "derived_findings": count(Finding.origin.like("derived:%")),
        "links": links,
    }


def format_report(session: Session, q: dict) -> str:
    batches = session.scalars(select(ImportBatch).order_by(ImportBatch.id)).all()
    lines = ["DATA QUALITY REPORT", "=" * 60]
    for b in batches:
        r = b.report or {}
        lines.append(f"Import #{b.id} {b.kind} {b.filename}")
        lines.append(f"  rows read {r.get('rows_read', 0)} · created {r.get('created', 0)} · merged into existing {r.get('merged_into_existing', 0)}")
        if "duplicates_in_file" in r:
            lines.append(f"  duplicates removed in this file: {r['duplicates_in_file']} "
                         f"(+{r.get('duplicates_merged_before_export', 0)} merged before export)")
        if r.get("skipped_invalid_url"):
            lines.append(f"  skipped (no usable URL): {len(r['skipped_invalid_url'])}")
        if r.get("fixes"):
            lines.append("  fixes: " + ", ".join(f"{k} {v}" for k, v in r["fixes"].items()))
    d = q["domains"]
    lines += [
        "",
        f"Findings: {q['total_findings']}  " + "  ".join(f"{k}={v}" for k, v in sorted(q["by_source"].items())),
        "Status:   " + "  ".join(f"{k}={v}" for k, v in sorted(q["by_status"].items())),
        f"Operators assigned: {q['with_operator']}",
        "",
        f"Domains: {d['total']}",
        f"  hosting/registrar/abuse from workbook: {d['manual_enrichment_from_workbook']}",
        f"  network-enriched (RDAP, DNS, CF, screenshot): {d['network_enriched']}  · waiting: {d['awaiting_network_enrichment']}",
        f"  category from workbook: {d['category_from_workbook']}  · suggested by rules: {d['category_suggested']}",
        f"  impersonation alerts: {d['impersonation']}",
        "",
        f"Derived findings (ad landings, links in text): {q['derived_findings']}",
        "Links: " + "  ".join(f"{k}={v}" for k, v in sorted(q["links"].items())),
        "",
        f"Needs review: {q['needs_review']}",
    ]
    lines += [f"  {k}: {v}" for k, v in q["needs_review_reasons"].items()]
    return "\n".join(lines)
