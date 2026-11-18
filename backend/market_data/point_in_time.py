"""Append-only observations. Historical availability must come from a trusted source.

An ordinary Yahoo backfill becomes available NOW, never at its historical bar date.
Query availability separately from ingestion time for reproducible research.
"""
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select
from database.models import BarRevision, Security, SecurityAlias, UniverseMembership
from .calendar import session_close


def aware(value):
    moment = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return moment.astimezone(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def record_bar(session, symbol, bar, source, now, market="US"):
    day = date.fromisoformat(str(bar.get("trade_date") or bar.get("date")))
    available = aware(bar["available_at"]) if bar.get("available_at") else now
    aliases = list(session.scalars(select(SecurityAlias).where(
        SecurityAlias.symbol == symbol, SecurityAlias.valid_from <= day,
        (SecurityAlias.valid_to.is_(None) | (SecurityAlias.valid_to > day)),
        SecurityAlias.available_at <= now)))
    if len(aliases) > 1:
        raise ValueError("ambiguous security mapping")
    security_id = aliases[0].security_id if aliases else "unverified-" + uuid5(NAMESPACE_URL, market + ":" + symbol).hex
    security = session.get(Security, security_id)
    if security is None:
        security = Security(id=security_id, market=market,
            currency={"US": "USD", "JP": "JPY", "HK": "HKD"}[market], provisional=True)
        session.add(security)
        session.flush()
    # Serializes revision allocation on PostgreSQL; caller transaction owns the lock.
    session.scalar(select(Security).where(Security.id == security_id).with_for_update())
    payload = {key: value for key, value in bar.items() if key != "available_at"}
    digest = sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
    latest = session.scalar(select(BarRevision).where(BarRevision.security_id == security_id,
        BarRevision.trade_date == day, BarRevision.source == source).order_by(BarRevision.revision.desc()).limit(1))
    if latest and latest.checksum == digest and latest.quality_status == "accepted":
        return
    if latest and latest.quality_status == "accepted" and available < utc(latest.available_at):
        raise ValueError("a revision cannot precede the previous observation")
    try:
        close = session_close(day, security.market)
        quality = "accepted" if close <= available <= now else "quarantined"
    except ValueError:
        quality = "quarantined"
    session.add(BarRevision(id=uuid4().hex, security_id=security_id, symbol=symbol,
        trade_date=day, source=source, revision=latest.revision + 1 if latest else 1,
        available_at=available, ingested_at=now, quality_status=quality, checksum=digest, payload=payload))
    session.flush()


def bars_as_of(sessions, security_id, as_of, *, source, known_at=None):
    cutoff = aware(as_of)
    with sessions() as session:
        query = select(BarRevision).where(BarRevision.security_id == security_id,
            BarRevision.source == source, BarRevision.available_at <= cutoff,
            BarRevision.trade_date <= cutoff.date())
        if known_at:
            query = query.where(BarRevision.ingested_at <= aware(known_at))
        rows = session.scalars(query.order_by(BarRevision.trade_date, BarRevision.available_at, BarRevision.revision)).all()
        latest = {row.trade_date: row for row in rows}
        # A quarantined correction blocks that date instead of reviving an older value.
        return [{**row.payload, "trade_date": day.isoformat(), "security_id": security_id,
                 "available_at": utc(row.available_at).isoformat(), "revision": row.revision}
                for day, row in latest.items() if row.quality_status == "accepted"]


def import_security_master(sessions, payload):
    """Operator import; intervals are [valid_from, valid_to). Records are immutable."""
    with sessions.begin() as session:
        for item in payload.get("securities", []):
            if item["market"] not in {"US", "JP", "HK"}:
                raise ValueError("unsupported market")
            row = session.get(Security, item["id"])
            values = {k: item[k] for k in ("id", "market", "currency")}
            if row and any(getattr(row, k) != v for k, v in values.items()):
                raise ValueError("security identity is immutable")
            if row is None:
                session.add(Security(**values, provisional=False))
        session.flush()
        for key, model, fields in (
            ("aliases", SecurityAlias, ("security_id", "symbol")),
            ("memberships", UniverseMembership, ("security_id", "universe")),
        ):
            for item in payload.get(key, []):
                values = {field: item[field] for field in fields}
                values.update(valid_from=date.fromisoformat(item["valid_from"]),
                    valid_to=date.fromisoformat(item["valid_to"]) if item.get("valid_to") else None,
                    available_at=aware(item["available_at"]))
                if values["valid_to"] and values["valid_to"] <= values["valid_from"]:
                    raise ValueError("invalid validity interval")
                if session.get(Security, item["security_id"]) is None:
                    raise ValueError("unknown security_id")
                digest = sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
                if session.get(model, digest) is None:
                    session.add(model(id=digest, **values))


def universe_as_of(sessions, universe, as_of):
    cutoff = aware(as_of)
    with sessions() as session:
        rows = session.scalars(select(UniverseMembership).where(
            UniverseMembership.universe == universe, UniverseMembership.valid_from <= cutoff.date(),
            (UniverseMembership.valid_to.is_(None) | (UniverseMembership.valid_to > cutoff.date())),
            UniverseMembership.available_at <= cutoff))
        return sorted({row.security_id for row in rows})
