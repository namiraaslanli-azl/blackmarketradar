"""Enrichment against a local web server; DNS and RDAP are stubbed (no internet in CI)."""

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import select

from radar.config import get_settings
from radar.enrichment import netinfo, web
from radar.enrichment.worker import apply_result, collect, http_client
from radar.models import Evidence, Finding, Link
from radar.store import FindingIn, upsert_finding

ICON = b"\x00\x00\x01\x00fake-icon-bytes"
PAGE = """<!doctype html><html lang="az"><head><title>Pin-Up Kazino Azərbaycan</title>
<link rel="icon" href="/static/fav.ico"></head><body><h1>Pin-Up kazino</h1>
<p>Qeydiyyat bonusu 125% depozit, 250 free spin. Minimum depozit 10 AZN. Promo kod: PINUP777</p>
<p>Ödəniş: M10, Kapital Bank, USDT</p></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        port = self.server.server_address[1]
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/az/")
            self.end_headers()
        elif self.path == "/az/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Server", "cloudflare")
            self.send_header("CF-RAY", "abc")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/static/fav.ico":
            self.send_response(200)
            self.send_header("Content-Type", "image/x-icon")
            self.end_headers()
            self.wfile.write(ICON)
        elif self.path == "/mirror":
            body = f'<meta http-equiv="refresh" content="0; url=http://localhost:{port}/az/">'.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def stub_network(monkeypatch, tmp_path):
    monkeypatch.setattr(netinfo, "resolve", lambda host, **kw: netinfo.DnsInfo(
        a=["104.21.3.4"], ns=["ada.ns.cloudflare.com"], resolves=True))
    monkeypatch.setattr(netinfo, "rdap_domain", lambda client, d: netinfo.parse_rdap_domain(RDAP_DOMAIN))
    monkeypatch.setattr(netinfo, "rdap_ip", lambda client, ip: pytest.fail("no IP RDAP behind Cloudflare"))
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


RDAP_DOMAIN = {
    "events": [{"eventAction": "registration", "eventDate": "2025-01-02T00:00:00Z"}],
    "nameservers": [{"ldhName": "ADA.NS.CLOUDFLARE.COM"}],
    "entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["fn", {}, "text", "NameCheap, Inc."]]],
                  "entities": [{"roles": ["abuse"], "vcardArray": ["vcard", [["email", {}, "text", "abuse@namecheap.com"]]]}]}],
}


def test_rdap_and_whois_parsing():
    d = netinfo.parse_rdap_domain(RDAP_DOMAIN)
    assert d["registrar"] == "NameCheap, Inc." and d["registrar_abuse_email"] == "abuse@namecheap.com"
    assert d["nameservers"] == ["ada.ns.cloudflare.com"]
    w = netinfo.parse_whois("Registrar: Example Reg\nRegistrar Abuse Contact Email: abuse@reg.az\nName Server: NS1.X.AZ\n")
    assert w["registrar"] == "Example Reg" and w["registrar_abuse_email"] == "abuse@reg.az" and w["nameservers"] == ["ns1.x.az"]
    assert netinfo.is_cloudflare_ip("104.21.3.4") and not netinfo.is_cloudflare_ip("8.8.8.8")


def test_favicon_hash_is_shodan_compatible():
    # Shodan hashes base64 *with* a newline every 76 chars; plain b64encode gives other values
    import base64

    import mmh3

    data = bytes(range(256))
    assert web.favicon_hash(data) == mmh3.hash(base64.encodebytes(data))
    assert web.favicon_hash(data) != mmh3.hash(base64.b64encode(data))


def test_collect_and_apply(session, server, stub_network):
    f = upsert_finding(session, FindingIn(url=f"http://{server}/", category="Birbaşa Mərc Saytı",
                                          suggested_action="İKTA DNS Blocklist", category_suggested=True)).finding
    host = server.split(":")[0]
    with http_client() as client:
        data = collect(host, f"http://{server}/", client, ["kazino", "bonus", "free spin", "depozit", "pin-up"])
    assert [h["status"] for h in data["http"]["chain"]] == [302, 200]
    assert data["http"]["title"] == "Pin-Up Kazino Azərbaycan"
    assert data["cloudflare"] == {"is_cloudflare": True, "evidence": ["ip_range", "nameservers", "http_headers"]}
    assert data["abuse"] == {"hosting": "abuse@cloudflare.com", "registrar": "abuse@namecheap.com",
                             "registrar_name": "NameCheap, Inc.", "hosting_name": "Cloudflare Inc."}
    c = data["content"]
    assert c["is_gambling"] and {"azn", "azerbaijan", "lang_az"} <= set(c["az_targeting"])
    assert c["promo_codes"] == ["PINUP777"]

    apply_result(session, f, data)
    session.flush()
    assert f.is_live and f.enriched_at is not None
    assert {"cloudflare", "az_targeting", "gambling_content"} <= set(f.tags)
    assert f.suggested_action.endswith("Cloudflare Abuse")
    kinds = {e.kind: e for e in session.scalars(select(Evidence).where(Evidence.finding_id == f.id))}
    assert set(kinds) == {"html", "favicon"}
    stored = Path(stub_network) / kinds["html"].path
    assert stored.read_bytes() == PAGE.encode()
    import hashlib
    assert kinds["html"].sha256 == hashlib.sha256(PAGE.encode()).hexdigest()
    types = {l.link_type for l in session.scalars(select(Link).where(Link.src_id == f.id))}
    assert {"favicon_hash", "payment_method", "promo_code"} <= types


def test_meta_refresh_to_other_host_creates_redirect_finding(session, server, stub_network):
    f = upsert_finding(session, FindingIn(url=f"http://{server}/mirror")).finding
    with http_client() as client:
        data = collect(server.split(":")[0], f"http://{server}/mirror", client, ["kazino"])
    assert data["http"]["chain"][0]["via"] == "meta"
    apply_result(session, f, data)
    session.flush()
    target = session.scalar(select(Finding).where(Finding.canonical_key == "domain:localhost"))
    assert target is not None and "redirect_target" in target.tags
    assert "redirects" in f.tags


@pytest.mark.skipif(not os.path.exists("/opt/pw-browsers") and not os.environ.get("CHROMIUM_PATH"),
                    reason="no Chromium available")
def test_screenshot(server, monkeypatch):
    monkeypatch.setenv("CHROMIUM_PATH", os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"))
    get_settings.cache_clear()
    from radar.enrichment.screenshot import browser, capture

    with browser() as ctx:
        cap = capture(ctx, f"http://{server}/")
    get_settings.cache_clear()
    assert cap.png.startswith(b"\x89PNG") and cap.final_url.endswith("/az/")
    assert b"Pin-Up kazino" in cap.html
