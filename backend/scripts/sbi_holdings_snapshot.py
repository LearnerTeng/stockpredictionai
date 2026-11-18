"""将已核对的 SBI NISA 持仓快照同步到现有持仓。
Apply a verified SBI NISA holdings snapshot to existing positions.
"""
import argparse
import csv
from datetime import datetime
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.models import Position, SbiRecord
from database.session import create_database_engine, session_factory
from market_data.point_in_time import utc
from sqlalchemy import select
from trading.sbi import JST, SCALE, SbiImport

SUMMARY = ["評価額 (円)", "評価損益 (円)", "評価損益 (率・%)", "前日比 (円)", "前日比 (率・%)"]
HEADER = ["ファンド名", "積立設定中", "定期売却設定中", "保有口数 (口)", "売却注文中 (口)",
          "基準価額 (円)", "取得単価 (円)", "評価額 (円)", "取得金額 (円)", "評価損益 (円)",
          "評価損益 (率・%)", "評価損益 前日比 (円)", "評価損益 前日比 (率・%)"]
SECTION = re.compile(r"保有状況-金額指定-NISA \((成長|つみたて)\)預り \((\d+)件\)")
BUCKETS = {"成長": "growth", "つみたて": "tsumitate"}
FIELDS = ("quantity", "last_price", "average_cost", "reported_market_value", "reported_cost_basis")


def normalized_name(name):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name)).casefold()


def integer(value, *, signed=False):
    if not re.fullmatch(r"[+-]?[0-9]{1,14}" if signed else r"[0-9]{1,14}", value):
        raise ValueError("Unrecognized numeric field in SBI export")
    return int(value)


def totals(positions):
    return tuple(sum(row[key] for row in positions) for key in ("reported_market_value", "pnl"))


def parse(raw):
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = raw.decode("cp932")
    rows = [row for row in csv.reader(StringIO(decoded, newline=""), strict=True) if any(row)]
    if len(rows) < 6 or rows[0] != ["保有状況-全体"] or rows[1] != SUMMARY or len(rows[2]) != len(SUMMARY):
        raise ValueError("Expected an SBI 保有ファンド holdings export with a total summary")
    expected = integer(rows[2][0]), integer(rows[2][1], signed=True)
    positions = {}
    seen_buckets = set()
    index = 3
    while index < len(rows):
        heading, summary, subtotal, header = rows[index:index + 4]
        match = SECTION.fullmatch(heading[0]) if len(heading) == 1 else None
        if not match or summary != SUMMARY or len(subtotal) != len(SUMMARY) or header != HEADER:
            raise ValueError("Unsupported account section or holdings columns")
        bucket = BUCKETS[match[1]]
        count = int(match[2])
        if bucket in seen_buckets or count <= 0:
            raise ValueError("Duplicate or empty account section")
        seen_buckets.add(bucket)
        group = []
        for entry in rows[index + 4:index + 4 + count]:
            if len(entry) != len(HEADER) or not entry[0].strip():
                raise ValueError("Incomplete fund position")
            key = bucket, normalized_name(entry[0])
            quantity, pending, nav, cost, value, basis = (integer(x) for x in entry[3:9])
            pnl = integer(entry[9], signed=True)
            if not quantity or not nav or pending > quantity or value - basis != pnl or key in positions:
                raise ValueError("Inconsistent fund position")
            position = dict(zip(FIELDS, (quantity, nav, cost, value, basis)), pending_sell=pending, pnl=pnl)
            positions[key] = position
            group.append(position)
        if len(group) != count or totals(group) != (integer(subtotal[0]), integer(subtotal[1], signed=True)):
            raise ValueError("SBI account subtotals do not reconcile")
        index += 4 + count
    if set(BUCKETS.values()) != seen_buckets or totals(positions.values()) != expected:
        raise ValueError("SBI total or NISA account coverage does not reconcile")
    return positions


def update(sessions, portfolio_id, raw, observed_at, *, apply):
    positions = parse(raw)
    fingerprint = sha256(raw).hexdigest()
    service = SbiImport(sessions)
    with sessions.begin() as session:
        portfolio = service._lock(session, portfolio_id)
        return update_locked(session, portfolio, service, positions, fingerprint, observed_at, apply)


def update_locked(session, portfolio, service, positions, fingerprint, observed_at, apply):
    portfolio_id = portfolio.id
    latest = session.get(SbiRecord, (portfolio_id, "holdings", "latest"))
    audit = session.get(SbiRecord, (portfolio_id, "holdings", fingerprint))
    if audit:
        return {"status": "already_applied", "observed_at": audit.data["observed_at"]}
    ledger_kinds = ("config", "seed", "trade", "valuation")
    if session.scalar(select(SbiRecord.id).where(
        SbiRecord.portfolio_id == portfolio_id, SbiRecord.kind.in_(ledger_kinds)).limit(1)):
        raise ValueError("This account already has an incremental ledger. Reconcile the ledger before replacing its baseline.")
    if latest and datetime.fromisoformat(latest.data["observed_at"]) >= observed_at:
        raise ValueError("The export is older than or equal to the last recorded snapshot")
    existing = session.scalars(select(Position).where(Position.portfolio_id == portfolio_id)).all()
    mapped = {(row.account_bucket, normalized_name(row.name)): row for row in existing}
    if len(mapped) != len(existing) or set(mapped) != set(positions):
        raise ValueError("Export and DB fund names or account buckets differ; review the mapping before writing")
    if any(row.currency != "JPY" or row.price_scale != SCALE or utc(row.updated_at) > observed_at
           for row in existing):
        raise ValueError("DB positions have a different currency or price scale, or a later update")
    value, pnl = totals(positions.values())
    info = dict(status="applied" if apply else "preview", observed_at=observed_at.isoformat(),
                positions=len(positions), market_value_jpy=value, cost_basis_jpy=value - pnl, pnl_jpy=pnl,
                positions_with_pending_sell=sum(row["pending_sell"] > 0 for row in positions.values()))
    if apply:
        changed_at = datetime.now(JST)
        previous = {}
        for key, row in mapped.items():
            previous[row.symbol] = {field: getattr(row, field) for field in (*FIELDS, "source")}
            previous[row.symbol]["updated_at"] = row.updated_at.isoformat()
            for field in FIELDS:
                setattr(row, field, positions[key][field])
            row.source, row.updated_at = "sbi-holdings-csv", observed_at
        service._record(session, portfolio_id, "holdings", fingerprint, {
            **info, "previous_portfolio_updated_at": portfolio.updated_at.isoformat(), "previous": previous,
            "pending_sell_units": {row.symbol: positions[key]["pending_sell"] for key, row in mapped.items()},
        }, changed_at)
        service._record(session, portfolio_id, "holdings", "latest", {**info, "sha256": fingerprint}, changed_at)
        portfolio.updated_at = observed_at
    return info


def observed_timestamp(filename):
    match = re.fullmatch(r"fundHoldings_(\d{14})(?: \(\d+\))?\.csv", filename, re.IGNORECASE)
    if not match:
        raise ValueError("Keep the original SBI timestamped fundHoldings filename")
    observed_at = datetime.strptime(match[1], "%Y%m%d%H%M%S").replace(tzinfo=JST)
    if observed_at > datetime.now(JST):
        raise ValueError("The export timestamp is in the future")
    return observed_at


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--portfolio", default="nisa")
    parser.add_argument("--apply", action="store_true", help="Commit the validated snapshot to the database")
    args = parser.parse_args()
    try:
        observed_at = observed_timestamp(args.csv.name)
        with args.csv.open("rb") as handle:
            raw = handle.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Holdings export exceeds 1 MB")
        engine = create_database_engine(connect_args={"connect_timeout": 4})
        try:
            result = update(session_factory(engine), args.portfolio, raw, observed_at, apply=args.apply)
        finally:
            engine.dispose()
    except (ValueError, csv.Error, OSError) as error:
        parser.exit(1, f"Snapshot rejected: {error}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
