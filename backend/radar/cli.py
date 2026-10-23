"""Command line: `radar --help`."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import typer
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from radar.db import session_scope
from radar.models import Finding, Keyword, Operator, WhitelistEntry
from radar.seeds import KEYWORDS, OPERATORS, WHITELIST

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def migrate() -> None:
    """Apply database migrations."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    command.upgrade(cfg, "head")


def seed_reference(session) -> dict:
    n_ops = n_kw = n_wl = 0
    for slug, name, aliases, licensed in OPERATORS:
        r = session.execute(pg_insert(Operator).values(slug=slug, name=name, aliases=aliases, is_licensed=licensed)
                            .on_conflict_do_nothing(index_elements=["slug"]))
        n_ops += r.rowcount
    for term, kind, lang in KEYWORDS:
        r = session.execute(pg_insert(Keyword).values(term=term, kind=kind, lang=lang or None)
                            .on_conflict_do_nothing(index_elements=["term"]))
        n_kw += r.rowcount
    for kind, value, owner in WHITELIST:
        r = session.execute(pg_insert(WhitelistEntry).values(kind=kind, value=value, owner=owner)
                            .on_conflict_do_nothing(constraint="uq_whitelist_kind_value"))
        n_wl += r.rowcount
    return {"operators": n_ops, "keywords": n_kw, "whitelist": n_wl}


@app.command()
def seed() -> None:
    """Load operators, keywords and the licensed whitelist (idempotent)."""
    with session_scope() as s:
        typer.echo(json.dumps(seed_reference(s)))


def _parse_seen(seen_at: str | None) -> datetime | None:
    return datetime.fromisoformat(seen_at).replace(tzinfo=timezone.utc) if seen_at else None


def _finish_import(s, batch) -> None:
    from radar.linker import run_linker
    from radar.quality import quality_report

    def derived_since():
        return list(s.scalars(select(Finding).where(Finding.origin.like("derived:%"),
                                                    Finding.created_at >= batch.started_at)))

    link = run_linker(s)
    run_linker(s, derived_since())
    for f in derived_since():  # objects found while linking imported history are backfill too
        if "imported" not in (f.tags or []):
            f.tags = [*(f.tags or []), "imported"]
    batch.report = {**batch.report, "linker": link.as_dict(), "quality": quality_report(s)}


@app.command("import-seed")
def import_seed(path: Path, seen_at: str = typer.Option(None, help="ISO date to use as first_seen when a row has none")) -> None:
    """Import the normalized findings seed (.csv or .xlsx with a "Findings" sheet)."""
    from radar.importers.seed_csv import import_seed_csv

    with session_scope() as s:
        seed_reference(s)
        batch = import_seed_csv(s, path, _parse_seen(seen_at))
        _finish_import(s, batch)
        typer.echo(json.dumps(batch.report, ensure_ascii=False, indent=2, default=str))


@app.command("import-workbook")
def import_workbook_cmd(path: Path, seen_at: str = typer.Option(None)) -> None:
    """Import the original weekly .xlsx report (all sheets)."""
    from radar.importers.workbook import import_workbook

    with session_scope() as s:
        seed_reference(s)
        batch = import_workbook(s, path, _parse_seen(seen_at))
        _finish_import(s, batch)
        typer.echo(json.dumps(batch.report, ensure_ascii=False, indent=2, default=str))


@app.command("import-apify")
def import_apify_cmd(paths: list[Path]) -> None:
    """Import Apify dataset exports (JSON, JSONL or CSV)."""
    from radar.importers.apify import import_apify
    from radar.linker import run_linker

    with session_scope() as s:
        for p in paths:
            batch = import_apify(s, p)
            typer.echo(f"{p.name}: {json.dumps(batch.report, ensure_ascii=False)}")
        typer.echo(json.dumps(run_linker(s).as_dict(), ensure_ascii=False))


@app.command()
def link() -> None:
    """Re-run the offline linker over all findings."""
    from radar.linker import run_linker

    with session_scope() as s:
        typer.echo(json.dumps(run_linker(s).as_dict(), ensure_ascii=False, indent=2))


@app.command()
def enrich(
    limit: int = typer.Option(0, help="max domains (0 = all due)"),
    force: bool = typer.Option(False, help="ignore refresh interval"),
    no_screenshot: bool = typer.Option(False),
    queue: bool = typer.Option(False, help="enqueue Celery tasks instead of running inline"),
) -> None:
    """Enrich organic domains: RDAP/WHOIS, DNS, Cloudflare, abuse contact, redirects, HTML, favicon, screenshot."""
    from radar.enrichment.worker import due_domain_ids, enrich_many

    with session_scope() as s:
        ids = due_domain_ids(s, limit=limit or None, force=force)
    typer.echo(f"{len(ids)} domains due")
    if queue:
        from radar.tasks import enrich_finding_task

        for i in ids:
            enrich_finding_task.delay(i, screenshot=not no_screenshot)
        typer.echo("queued")
        return
    summary = enrich_many(ids, screenshot=not no_screenshot)
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))


@app.command()
def collectors() -> None:
    """List collectors, schedule, enabled state and missing secrets."""
    from radar.collectors import REGISTRY
    from radar.collectors.base import effective_params

    with session_scope() as s:
        for name, c in REGISTRY.items():
            enabled, _ = effective_params(s, c)
            missing = c.missing_secrets()
            typer.echo(f"{name:14} {'on ' if enabled else 'off'}  {c.schedule}  "
                       f"{'needs ' + ', '.join(missing) if missing else 'ready'}")


@app.command()
def collect(name: str, param: list[str] = typer.Option([], "--param", "-p", help="key=value override (JSON values ok)"),
            force: bool = typer.Option(False, help="run even if disabled")) -> None:
    """Run one collector now, e.g. `radar collect ct_crtsh -p days=1`."""
    from radar.collectors import run_collector

    override = {}
    for kv in param:
        k, _, v = kv.partition("=")
        try:
            override[k] = json.loads(v)
        except json.JSONDecodeError:
            override[k] = v
    typer.echo(json.dumps(run_collector(name, override, force=force), ensure_ascii=False, indent=2))


@app.command()
def certstream(flush_seconds: int = 60) -> None:
    """Consume the live CertStream feed forever (run as its own service)."""
    from radar.collectors.ct import certstream_loop

    certstream_loop(flush_seconds=flush_seconds)


@app.command("telegram-login")
def telegram_login(phone: str = typer.Option(..., prompt="Telegram phone (+994...)")) -> None:
    """One-time interactive login of the dedicated Telegram account; stores the session file."""
    import asyncio
    import os

    from radar.collectors.telegram import interactive_login
    from radar.config import get_settings

    session = asyncio.run(interactive_login(phone))
    path = get_settings().telegram_session_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(session)
    os.chmod(path, 0o600)
    typer.echo(f"saved session to {path}")


@app.command()
def track(kind: str, value: str, note: str = typer.Option(None)) -> None:
    """Add a tracked account / page / channel / hashtag, e.g. `radar track tiktok_account kod_satisi`."""
    from radar.models import TARGET_KINDS, TrackedTarget

    if kind not in TARGET_KINDS:
        raise typer.BadParameter(f"kind must be one of {', '.join(TARGET_KINDS)}")
    with session_scope() as s:
        s.execute(pg_insert(TrackedTarget).values(kind=kind, value=value.strip().lstrip("@#"), note=note)
                  .on_conflict_do_nothing(constraint="uq_tracked_kind_value"))
    typer.echo("ok")


@app.command()
def report(as_json: bool = typer.Option(False, "--json")) -> None:
    """Print the data-quality report."""
    from radar.quality import format_report, quality_report

    with session_scope() as s:
        q = quality_report(s)
        typer.echo(json.dumps(q, ensure_ascii=False, indent=2, default=str) if as_json else format_report(s, q))


if __name__ == "__main__":
    app()
