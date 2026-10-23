"""DNS, RDAP / WHOIS and Cloudflare detection."""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import asdict, dataclass, field

import dns.exception
import dns.resolver
import httpx

from radar.normalize import registrable_domain

CLOUDFLARE_V4 = [
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18",
    "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17",
    "162.158.0.0/15", "104.16.0.0/13", "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
]
CLOUDFLARE_V6 = ["2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32",
                 "2a06:98c0::/29", "2c0f:f248::/32"]
_CF_NETS = [ipaddress.ip_network(n) for n in CLOUDFLARE_V4 + CLOUDFLARE_V6]
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


@dataclass
class DnsInfo:
    a: list[str] = field(default_factory=list)
    aaaa: list[str] = field(default_factory=list)
    ns: list[str] = field(default_factory=list)
    mx: list[str] = field(default_factory=list)
    cname: list[str] = field(default_factory=list)
    resolves: bool = False
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def resolve(host: str, nameservers: list[str] | None = None, timeout: float = 5.0) -> DnsInfo:
    r = dns.resolver.Resolver()
    if nameservers:
        r.nameservers = nameservers
    r.lifetime = timeout
    info = DnsInfo()

    def q(name, rtype):
        try:
            return [str(x).rstrip(".").lower() if rtype != "MX" else str(x.exchange).rstrip(".").lower()
                    for x in r.resolve(name, rtype)]
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            return []
        except dns.exception.DNSException as exc:
            info.error = type(exc).__name__
            return []

    info.a = q(host, "A")
    info.aaaa = q(host, "AAAA")
    info.cname = q(host, "CNAME")
    zone = registrable_domain(host)
    info.ns = q(zone, "NS")
    info.mx = q(zone, "MX")
    info.resolves = bool(info.a or info.aaaa)
    return info


def is_cloudflare_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in _CF_NETS if n.version == addr.version)


def cloudflare_evidence(dnsinfo: DnsInfo, headers: dict[str, str] | None = None) -> list[str]:
    ev = []
    if any(is_cloudflare_ip(ip) for ip in dnsinfo.a + dnsinfo.aaaa):
        ev.append("ip_range")
    if any(ns.endswith(".ns.cloudflare.com") for ns in dnsinfo.ns):
        ev.append("nameservers")
    h = {k.lower(): v for k, v in (headers or {}).items()}
    if "cf-ray" in h or h.get("server", "").lower() == "cloudflare":
        ev.append("http_headers")
    return ev


# --- RDAP -------------------------------------------------------------------------------

def _vcard(entity: dict, key: str) -> str | None:
    for item in (entity.get("vcardArray") or [None, []])[1]:
        if item and item[0] == key:
            return item[3] if isinstance(item[3], str) else " ".join(map(str, item[3]))
    return None


def _walk_entities(entities: list[dict]):
    for e in entities or []:
        yield e
        yield from _walk_entities(e.get("entities", []))


def parse_rdap_domain(doc: dict) -> dict:
    out: dict = {"registrar": None, "registrar_abuse_email": None, "created": None, "expires": None,
                 "status": doc.get("status", []), "nameservers": [n.get("ldhName", "").lower() for n in doc.get("nameservers", [])]}
    for ev in doc.get("events", []):
        if ev.get("eventAction") == "registration":
            out["created"] = ev.get("eventDate")
        elif ev.get("eventAction") == "expiration":
            out["expires"] = ev.get("eventDate")
    for e in _walk_entities(doc.get("entities", [])):
        roles = e.get("roles", [])
        if "registrar" in roles and not out["registrar"]:
            out["registrar"] = _vcard(e, "fn")
        if "abuse" in roles and not out["registrar_abuse_email"]:
            out["registrar_abuse_email"] = _vcard(e, "email")
    return out


def parse_rdap_ip(doc: dict) -> dict:
    out = {"network": doc.get("name"), "country": doc.get("country"), "org": None, "abuse_email": None,
           "cidr": None}
    cidrs = doc.get("cidr0_cidrs") or []
    if cidrs:
        c = cidrs[0]
        out["cidr"] = f"{c.get('v4prefix') or c.get('v6prefix')}/{c.get('length')}"
    for e in _walk_entities(doc.get("entities", [])):
        roles = e.get("roles", [])
        if ("registrant" in roles or "administrative" in roles) and not out["org"]:
            out["org"] = _vcard(e, "fn")
        if "abuse" in roles and not out["abuse_email"]:
            out["abuse_email"] = _vcard(e, "email")
    if not out["org"]:
        out["org"] = doc.get("name")
    return out


def rdap_domain(client: httpx.Client, domain: str) -> dict | None:
    r = client.get(f"https://rdap.org/domain/{domain}", follow_redirects=True)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return parse_rdap_domain(r.json())


def rdap_ip(client: httpx.Client, ip: str) -> dict | None:
    r = client.get(f"https://rdap.org/ip/{ip}", follow_redirects=True)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return parse_rdap_ip(r.json())


# --- WHOIS fallback (ccTLDs without RDAP, e.g. .az) ------------------------------------

def _whois_query(server: str, query: str, timeout: float = 10.0) -> str:
    with socket.create_connection((server, 43), timeout=timeout) as s:
        s.sendall((query + "\r\n").encode())
        chunks = []
        while data := s.recv(4096):
            chunks.append(data)
    return b"".join(chunks).decode("utf-8", "replace")


def parse_whois(text: str) -> dict:
    def first(*labels):
        for lab in labels:
            m = re.search(rf"^\s*{lab}\s*:\s*(.+)$", text, re.I | re.M)
            if m and m.group(1).strip():
                return m.group(1).strip()
        return None

    abuse = first("Registrar Abuse Contact Email", "abuse-mailbox", "Abuse Email")
    if not abuse:
        emails = [e for e in _EMAIL_RE.findall(text) if "abuse" in e.lower()]
        abuse = emails[0] if emails else None
    return {
        "registrar": first("Registrar", "registrar", "Sponsoring Registrar"),
        "registrar_abuse_email": abuse,
        "created": first("Creation Date", "created", "Registered on"),
        "expires": first("Registry Expiry Date", "Expiration Date", "expires", "paid-till"),
        "status": [],
        "nameservers": [m.lower() for m in re.findall(r"^\s*(?:Name Server|nserver)\s*:\s*(\S+)", text, re.I | re.M)],
    }


def whois_domain(domain: str) -> dict | None:
    tld = domain.rsplit(".", 1)[-1]
    referral = _whois_query("whois.iana.org", tld)
    m = re.search(r"^whois:\s*(\S+)", referral, re.I | re.M)
    if not m:
        return None
    text = _whois_query(m.group(1), domain)
    return {**parse_whois(text), "whois_server": m.group(1)}
