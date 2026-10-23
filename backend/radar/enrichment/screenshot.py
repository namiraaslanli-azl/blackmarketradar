"""Full-page screenshots and rendered HTML with headless Chromium (Playwright)."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from radar.config import get_settings


@dataclass
class Capture:
    final_url: str
    png: bytes
    html: bytes
    status: int | None


@contextmanager
def browser():
    from playwright.sync_api import sync_playwright

    s = get_settings()
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=s.chromium_path or None, args=["--no-sandbox"])
        ctx = b.new_context(
            user_agent=s.http_user_agent, locale="az-AZ", timezone_id="Asia/Baku",
            viewport={"width": 412, "height": 915}, device_scale_factor=1, ignore_https_errors=True,
            extra_http_headers={"Accept-Language": s.accept_language},
        )
        try:
            yield ctx
        finally:
            ctx.close()
            b.close()


def capture(ctx, url: str, timeout_ms: int = 30000) -> Capture:
    page = ctx.new_page()
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # long-polling sites never go idle; the DOM is enough
            pass
        png = page.screenshot(full_page=True, timeout=timeout_ms)
        return Capture(final_url=page.url, png=png, html=page.content().encode(), status=resp.status if resp else None)
    finally:
        page.close()
