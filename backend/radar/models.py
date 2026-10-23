"""Unified data model. Every collector, importer and the UI work against these tables."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

SOURCES = (
    "organic_domain",
    "meta_ad",
    "tiktok_post",
    "tiktok_account",
    "instagram_post",
    "instagram_account",
    "facebook_post",
    "facebook_page",
    "telegram_channel",
    "telegram_post",
    "play_store_app",
    "app_store_app",
)

STATUSES = ("new", "confirmed", "false_positive", "reported", "blocked")

LINK_TYPES = (
    "operator",
    "favicon_hash",
    "redirect",
    "promo_code",
    "payment_method",
    "telegram_link",
    "app_package",
    "landing",
    "ad_cluster",
    "mentions_domain",
    "linked_account",
    "image_hash",
)

TARGET_KINDS = ("meta_page", "tiktok_account", "instagram_account", "facebook_page", "telegram_channel", "hashtag")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Operator(TimestampMixin, Base):
    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    is_licensed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    website: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class Finding(TimestampMixin, Base):
    __tablename__ = "findings"
    __table_args__ = (
        CheckConstraint(_in("source", SOURCES), name="ck_findings_source"),
        CheckConstraint(_in("status", STATUSES), name="ck_findings_status"),
        Index("ix_findings_source_status", "source", "status"),
        Index("ix_findings_first_seen", "first_seen"),
        Index("ix_findings_host", "host"),
        Index("ix_findings_tags", "tags", postgresql_using="gin"),
        Index("ix_findings_keywords", "matched_keywords", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(24), unique=True)
    source: Mapped[str] = mapped_column(String(32))
    entity_type: Mapped[str | None] = mapped_column(String(40))
    canonical_key: Mapped[str] = mapped_column(Text, unique=True)
    url: Mapped[str] = mapped_column(Text)
    host: Mapped[str | None] = mapped_column(Text)
    handle: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    media_urls: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    landing_url: Mapped[str | None] = mapped_column(Text)
    landing_raw: Mapped[str | None] = mapped_column(Text)
    advertiser: Mapped[str | None] = mapped_column(Text)

    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    operator_id: Mapped[int | None] = mapped_column(ForeignKey("operators.id", ondelete="SET NULL"))
    operator: Mapped[Operator | None] = relationship()
    brands: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    matched_keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")

    ai_label: Mapped[str | None] = mapped_column(String(32))
    ai_score: Mapped[float | None] = mapped_column(Float)
    ai_reason: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), default="new", server_default="new")
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_status: Mapped[str | None] = mapped_column(Text)
    complaint_status: Mapped[str | None] = mapped_column(Text)
    is_live: Mapped[bool | None] = mapped_column(Boolean)

    # analyst columns kept from the weekly workbook ("Kateqoriya", "Təklif Olunan Təsir Mexanizmi")
    category: Mapped[str | None] = mapped_column(Text)
    suggested_action: Mapped[str | None] = mapped_column(Text)
    category_suggested: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    review_reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    is_impersonation: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    views: Mapped[int | None] = mapped_column(BigInteger)
    followers: Mapped[int | None] = mapped_column(BigInteger)
    subscribers: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)

    enrichment: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    origin: Mapped[str | None] = mapped_column(Text)  # import file / collector name

    evidence: Mapped[list["Evidence"]] = relationship(back_populates="finding", order_by="Evidence.captured_at.desc()")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    finding: Mapped[Finding] = relationship(back_populates="evidence")
    kind: Mapped[str] = mapped_column(String(20))  # screenshot | html | favicon
    url: Mapped[str | None] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    bytes: Mapped[int] = mapped_column(BigInteger)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class Link(Base):
    __tablename__ = "links"
    __table_args__ = (
        CheckConstraint(_in("link_type", LINK_TYPES), name="ck_links_type"),
        UniqueConstraint(
            "src_id", "dst_id", "operator_id", "link_type", "value",
            name="uq_links_edge", postgresql_nulls_not_distinct=True,
        ),
        Index("ix_links_type_value", "link_type", "value"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    src_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    dst_id: Mapped[int | None] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("operators.id", ondelete="CASCADE"), index=True)
    link_type: Mapped[str] = mapped_column(String(24))
    value: Mapped[str] = mapped_column(Text, default="", server_default="")
    confidence: Mapped[float] = mapped_column(Float, default=1.0, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FindingEvent(Base):
    __tablename__ = "finding_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    kind: Mapped[str] = mapped_column(String(32))  # detected | redetected | status | enriched | label
    actor: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="generic")  # generic | brand | promo | game | payment
    lang: Mapped[str | None] = mapped_column(String(8))
    weight: Mapped[float] = mapped_column(Float, default=1.0, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WhitelistEntry(Base):
    __tablename__ = "whitelist"
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_whitelist_kind_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # domain | handle | app | brand
    value: Mapped[str] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(Text)  # Azerlotereya | Topaz | TFC
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrackedTarget(Base):
    """Accounts / pages / channels that collectors re-check on every run (editable in Settings)."""

    __tablename__ = "tracked_targets"
    __table_args__ = (
        UniqueConstraint("kind", "value", name="uq_tracked_kind_value"),
        CheckConstraint(_in("kind", TARGET_KINDS), name="ck_tracked_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))
    value: Mapped[str] = mapped_column(Text)  # username / page id / hashtag without '#'
    note: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    source_finding_id: Mapped[int | None] = mapped_column(ForeignKey("findings.id", ondelete="SET NULL"))
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CollectorConfig(Base):
    """Per-collector switch and parameters; defaults live in code, overrides here."""

    __tablename__ = "collector_config"

    name: Mapped[str] = mapped_column(String(48), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    params: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CollectorRun(Base):
    __tablename__ = "collector_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    collector: Mapped[str] = mapped_column(String(48), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | ok | partial | failed
    items_found: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    error_log: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    params: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # seed_csv | workbook | apify
    filename: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    report: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
