"""Telegram via MTProto (Telethon) with a dedicated account.

Per run:
1. search public channels by keyword (contacts.SearchRequest);
2. read new posts of tracked + known channels since the last seen message id, keeping posts
   with keywords or links; links / invites in posts become new channel findings through the
   linker (snowball discovery), payment rails and promo codes become links;
3. resolve invite links (t.me/+hash) to title + member count without joining.
Create the session once with `radar telegram-login` (asks for the login code).
"""

from __future__ import annotations

import asyncio
from datetime import timezone
from typing import Iterable

from sqlalchemy import select

from radar.collectors.base import Collector, Ctx
from radar.collectors.serp import rotate
from radar.config import get_settings
from radar.db import session_scope
from radar.extract import extract_urls, match_keywords
from radar.models import Finding
from radar.store import FindingIn, add_link, upsert_finding


def load_session() -> str:
    p = get_settings().telegram_session_path
    if not p.exists():
        raise RuntimeError(f"no Telegram session at {p}; run `radar telegram-login` first")
    return p.read_text().strip()


def make_client(session: str | None = None):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    s = get_settings()
    client = TelegramClient(StringSession(session or ""), int(s.telegram_api_id), s.telegram_api_hash,
                            device_model="Radar", app_version="1.0", lang_code="az", system_lang_code="az")
    client.flood_sleep_threshold = 120  # sleep through short FloodWaits automatically
    return client


def channel_to_finding(username: str | None, title: str | None, members: int | None, about: str | None,
                       terms: list[str], last_id: int | None = None, invite: str | None = None) -> FindingIn:
    url = f"https://t.me/{invite}" if invite else f"https://t.me/{username}"
    text = about or None
    kws = match_keywords(" ".join(filter(None, [title, username, about])), terms)
    enrichment = {"telegram": {"last_id": last_id}} if last_id else {}
    return FindingIn(url=url, title=title, text=text, subscribers=members, matched_keywords=kws,
                     tags=["cashier_channel"] if "kassa" in f"{title} {username}".lower() else [],
                     enrichment=enrichment, raw={"collector": "telegram"})


def message_to_finding(username: str, msg_id: int, text: str, views: int | None, date, terms: list[str]) -> FindingIn | None:
    kws = match_keywords(text, terms)
    links = extract_urls(text)
    if not kws and not links:
        return None
    return FindingIn(url=f"https://t.me/{username}/{msg_id}", text=text[:4000], views=views, matched_keywords=kws,
                     published_at=date.astimezone(timezone.utc) if date else None, handle=username,
                     raw={"collector": "telegram", "links": links[:50]})


def channels_to_read(limit: int, tracked: list[str]) -> list[tuple[str, int | None]]:
    with session_scope() as s:
        rows = s.execute(select(Finding.handle, Finding.enrichment).where(
            Finding.source == "telegram_channel", Finding.handle.is_not(None),
            Finding.status.in_(("new", "confirmed", "reported")),
            Finding.entity_type.in_(("telegram_channel", "telegram_group"))).order_by(Finding.last_seen.desc())).all()
    last = {h.lower(): (e or {}).get("telegram", {}).get("last_id") for h, e in rows if h and not h.startswith("+")}
    ordered = [t.lower().lstrip("@") for t in tracked] + [h for h in last if h not in tracked]
    return [(h, last.get(h)) for h in dict.fromkeys(ordered)][:limit]


def invites_to_check(limit: int) -> list[str]:
    with session_scope() as s:
        return [h for h in s.scalars(select(Finding.handle).where(
            Finding.source == "telegram_channel", Finding.handle.like("+%"), Finding.subscribers.is_(None)).limit(limit)) if h]


class TelegramCollector(Collector):
    name = "telegram"
    title = "Telegram (axtarış, kanallar, dəvət linkləri)"
    schedule = {"minute": 45, "hour": "*/2"}
    requires = ("telegram_api_id", "telegram_api_hash")
    defaults = {"max_search_terms": 25, "max_channels": 150, "messages_per_channel": 100, "max_invites": 40,
                "max_flood_wait": 600}

    def missing_secrets(self) -> list[str]:
        missing = super().missing_secrets()
        if not get_settings().telegram_session_path.exists():
            missing.append("Telegram session (run `radar telegram-login`)")
        return missing

    def collect(self, ctx: Ctx) -> Iterable[FindingIn]:
        return asyncio.run(self._collect(ctx))

    async def _collect(self, ctx: Ctx) -> list[FindingIn]:
        from telethon import errors, functions, types

        p, out, terms = ctx.params, [], ctx.terms()
        async with make_client(load_session()) as client:
            # 1. search
            for term in rotate(sorted({t for t in ctx.terms("brand", "promo", "generic", "payment") if len(t) >= 4}),
                               p["max_search_terms"]):
                try:
                    res = await client(functions.contacts.SearchRequest(q=term, limit=50))
                except errors.FloodWaitError as e:
                    ctx.error(f"search flood wait {e.seconds}s — stopping search")
                    break
                for chat in res.chats:
                    if not isinstance(chat, types.Channel) or not chat.username:
                        continue
                    fin = channel_to_finding(chat.username, chat.title, getattr(chat, "participants_count", None),
                                             None, terms)
                    if fin.matched_keywords:
                        fin.tags.append("telegram_search")
                        fin.raw["search"] = term
                        out.append(fin)
            # 2. read channels
            for username, last_id in channels_to_read(p["max_channels"], ctx.targets.get("telegram_channel", [])):
                try:
                    entity = await client.get_entity(username)
                    if not isinstance(entity, types.Channel):
                        continue
                    full = await client(functions.channels.GetFullChannelRequest(entity))
                    newest = last_id or 0
                    async for msg in client.iter_messages(entity, min_id=last_id or 0, limit=p["messages_per_channel"]):
                        newest = max(newest, msg.id)
                        if msg.message:
                            post = message_to_finding(username, msg.id, msg.message, msg.views, msg.date, terms)
                            if post:
                                out.append(post)
                    out.append(channel_to_finding(username, entity.title, full.full_chat.participants_count,
                                                  full.full_chat.about, terms, last_id=newest or None))
                    ctx.mark_target("telegram_channel", username)
                except errors.FloodWaitError as e:
                    if e.seconds > p["max_flood_wait"]:
                        ctx.error(f"flood wait {e.seconds}s at {username} — stopping reads")
                        break
                    await asyncio.sleep(e.seconds)
                except (ValueError, errors.RPCError) as exc:  # renamed / deleted / private
                    ctx.error(f"{username}: {exc!r}"[:200])
            # 3. invite links
            for invite in invites_to_check(p["max_invites"]):
                try:
                    r = await client(functions.messages.CheckChatInviteRequest(hash=invite.lstrip("+")))
                except errors.FloodWaitError as e:
                    ctx.error(f"invite flood wait {e.seconds}s")
                    break
                except errors.RPCError as exc:
                    ctx.error(f"invite {invite}: {exc!r}"[:200])
                    continue
                chat = getattr(r, "chat", None)
                title = getattr(r, "title", None) or getattr(chat, "title", None)
                members = getattr(r, "participants_count", None) or getattr(chat, "participants_count", None)
                out.append(channel_to_finding(None, title, members, getattr(r, "about", None), terms, invite=invite))
        return out

    def after_upsert(self, session, finding, item, ctx) -> None:
        if finding.source != "telegram_post" or not finding.handle:
            return
        channel = upsert_finding(session, FindingIn(url=f"https://t.me/{finding.handle}", origin="collector:telegram"),
                                 status_policy="keep", actor=self.name).finding
        add_link(session, finding.id, "linked_account", dst_id=channel.id, value=finding.handle)
        if finding.operator_id is None and channel.operator_id:
            finding.operator_id = channel.operator_id


async def interactive_login(phone: str) -> str:
    client = make_client()
    await client.start(phone=phone)  # prompts for the code (and 2FA password) on the terminal
    session = client.session.save()
    await client.disconnect()
    return session
