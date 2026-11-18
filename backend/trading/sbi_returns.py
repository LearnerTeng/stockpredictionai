"""保存 SBI 按日收益快照和逐基金交易履历。
Store dated SBI return snapshots and per-fund transaction history.
"""
import csv
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from io import StringIO
import re

from sqlalchemy import select
from database.models import Position, SbiRecord
from scripts.sbi_holdings_snapshot import FIELDS, integer, normalized_name, parse as parse_holdings, update_locked
from trading.sbi import JST, SbiImport

RETURN_HEADER = ["保有状況", "ファンド名", "口座種別", "取引種別", "評価金額", "前年末評価金額",
                 "売却金額", "分配金額", "買付金額", "手数料", "トータルリターン（円）", "トータルリターン（率）"]
HISTORY_HEADER = ["発生日", "取引区分", "口座種別", "取引種別", "数量(口)", "金額(円)", "費用",
                  "分配金内訳(普通分配金)", "分配金内訳(特別分配金)", "当日基準価額", "保有数量", "評価金額", "個別元本"]
ACCOUNTS = {"NISA (成長)": "growth", "NISA (つみたて)": "tsumitate"}
RETURN_FIELDS = ("value", "prior_year_value", "sold", "distributions", "purchases", "fees", "return_jpy")
EVENT_FIELDS = ("units", "amount", "fee", "ordinary", "special", "nav", "holding_units", "value", "principal")
FUND_CODE = re.compile(r"[A-Z0-9]{8}")


def csv_entries(raw, header):
    try:
        source = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        source = raw.decode("cp932")
    rows = csv.reader(StringIO(source, newline=""), strict=True)
    if next(rows, None) != header:
        raise ValueError("Select the original CSV for the matching SBI page")
    for row in rows:
        if not any(row):
            continue
        if len(row) != len(header):
            raise ValueError(f"Incomplete SBI CSV row {rows.line_num}")
        yield row


def parse_returns(raw):
    result = {}
    for state, name, account, order, *values in csv_entries(raw, RETURN_HEADER):
        if state not in ("保有中", "解約済") or account not in ACCOUNTS or order != "金額" or not name.strip():
            raise ValueError("Expected all-period NISA amount-based fund returns")
        bucket = ACCOUNTS[account]
        key = bucket, normalized_name(name)
        if key in result or len(name) > 255 or not re.fullmatch(r"[+-]?[0-9]{1,14}(?:\.[0-9]{1,4})?%", values[-1]):
            raise ValueError("Duplicate fund/account or invalid SBI return rate")
        amounts = dict(zip(RETURN_FIELDS, (integer(value, signed=i == 6) for i, value in enumerate(values[:-1]))))
        if amounts["prior_year_value"] != 0:
            raise ValueError("Export SBI total returns with 全期間 (累計) selected")
        if amounts["value"] + amounts["sold"] + amounts["distributions"] - amounts["purchases"] - amounts["fees"] != amounts["return_jpy"]:
            raise ValueError("SBI return amounts do not reconcile")
        held = state == "保有中"
        if not held and amounts["value"]:
            raise ValueError("A closed fund has a nonzero market value")
        result[key] = dict(bucket=bucket, name=name, held=held, return_pct=float(Decimal(values[-1][:-1])), **amounts)
    if not result:
        raise ValueError("SBI return CSV is empty")
    return result


def parse_history(raw, as_of):
    result = []
    for day, action, account, order, *numbers in csv_entries(raw, HISTORY_HEADER):
        event_day = date.fromisoformat(day.replace("/", "-"))
        if event_day > as_of or account not in ACCOUNTS or order != "金額" or not action or len(action) > 60:
            raise ValueError("Invalid SBI transaction history date or account")
        values = dict(zip(EVENT_FIELDS, (integer(value) for value in numbers)))
        result.append(dict(day=event_day.isoformat(), action=action, bucket=ACCOUNTS[account], **values))
    if not result:
        raise ValueError("SBI fund transaction history is empty")
    return sorted(result, key=lambda row: row["day"])


def fund_map(names, returns):
    records = {normalized_name(name): code for code, name in names.items()}
    if (len(records) != len(names) or set(records) != {name for _, name in returns}
            or any(not FUND_CODE.fullmatch(code) for code in names)):
        raise ValueError("Match every fund in the SBI return CSV to its 履歴 page code and name")
    return records


def save_report(sessions, portfolio_id, as_of, returns_raw, expected_return, holdings_raw=None,
                names=None, history=None, apply=False, holdings_observed_at=None):
    if as_of > datetime.now(JST).date():
        raise ValueError("SBI calculation date is in the future")
    returns = parse_returns(returns_raw)
    if sum(row["return_jpy"] for row in returns.values()) != expected_return:
        raise ValueError("CSV total does not match the SBI all-period total shown on the page")
    # 对照在持基金和市值，确认两份导出使用同一估值口径。
    # Reconcile held funds and market values across the two exports.
    snapshots = parse_holdings(holdings_raw) if holdings_raw is not None else {}
    open_funds = {key for key, row in returns.items() if row["held"]}
    if holdings_raw is not None:
        if set(snapshots) != open_funds or any(snapshots[key]["reported_market_value"] != returns[key]["value"] for key in snapshots):
            raise ValueError("Holdings export does not match the return list; download both after SBI updates")
    history = history or {}
    if history and not names:
        raise ValueError("Transaction files need a fund code and the fund name from each 履歴 page")
    events = {code: parse_history(raw, as_of) for code, raw in history.items()}
    service = SbiImport(sessions)
    now = datetime.now(JST)
    # 持仓、收益和履历在同一组合锁和事务下处理。
    # Process holdings, returns and history under one portfolio lock and transaction.
    with sessions.begin() as session:
        portfolio = service._lock(session, portfolio_id)
        previous = sorted(service._rows(session, portfolio_id, "fund_return"), key=lambda row: row.id)
        if not names and previous:
            names = {row["code"]: row["name"] for row in previous[-1].data["funds"]}
        codes = fund_map(names or {}, returns)
        if not set(events) <= set(names):
            raise ValueError("Unknown fund in the history import")
        if any(set(row["bucket"] for row in series) != {bucket for bucket, name in returns if codes[name] == code}
               for code, series in events.items()):
            raise ValueError("History account groups differ from the total-return list")
        if holdings_observed_at is not None and snapshots:
            update_locked(session, portfolio, service, snapshots, sha256(holdings_raw).hexdigest(),
                          holdings_observed_at, apply)
        positions = {(row.account_bucket, normalized_name(row.name)): row.symbol
                     for row in session.scalars(select(Position).where(Position.portfolio_id == portfolio_id))}
        result = []
        for (bucket, name), row in returns.items():
            snapshot = snapshots.get((bucket, name))
            result.append(dict(**row, code=codes[name], symbol=positions.get((bucket, name)),
                               holdings={key: snapshot[key] for key in FIELDS} if snapshot else None))
        day = as_of.isoformat()
        old = session.get(SbiRecord, (portfolio_id, "fund_return", day))
        captured_at = holdings_observed_at.isoformat() if holdings_observed_at else None
        # 仅重导当日收益且市值一致时，保留已核对的持仓明细。
        # For a returns-only reimport, keep verified same-day holdings where the valuation still matches.
        if old and not snapshots:
            old_funds = {(row["code"], row["bucket"]): row for row in old.data["funds"]}
            for row in result:
                prior = old_funds.get((row["code"], row["bucket"]))
                if prior and prior["value"] == row["value"]:
                    row["holdings"] = prior["holdings"]
            captured_at = old.data.get("holdings_observed_at")
        totals = {key: sum(row[key] for row in result) for key in RETURN_FIELDS}
        denominator = totals["purchases"] + totals["fees"]
        totals["return_pct"] = round(totals["return_jpy"] / denominator * 100, 2) if denominator else None
        report = dict(as_of=day, totals=totals, funds=result, holdings_observed_at=captured_at, returns_sha256=sha256(returns_raw).hexdigest())
        for code, series in events.items():
            # 核对完整履历，同时保留重复成交的计数。
            # Check history completeness while preserving the count of identical transactions.
            prior = session.get(SbiRecord, (portfolio_id, "fund_history", code))
            if prior and (prior.data["as_of"] > day or Counter(map(event_key, prior.data["events"])) - Counter(map(event_key, series))):
                raise ValueError(f"History for {code} would replace previously recorded rows; check the full-period filter")
            if snapshots:
                for key in open_funds:
                    if codes[key[1]] != code:
                        continue
                    last_day = max(row["day"] for row in series if row["bucket"] == key[0])
                    latest_units = {row["holding_units"] for row in series if row["bucket"] == key[0] and row["day"] == last_day}
                    if snapshots[key]["quantity"] not in latest_units:
                        raise ValueError(f"History and current holding units do not reconcile for {code}")
            payload = dict(code=code, as_of=day, events=series, sha256=sha256(history[code]).hexdigest())
            if apply and (not prior or prior.data != payload):
                service._record(session, portfolio_id, "fund_history", code, payload, now)
        if apply and (not old or old.data != report):
            service._record(session, portfolio_id, "fund_return", day, report, now)
        return dict(as_of=day, funds=len(result), open_funds=len(open_funds),
                    histories=len(events), events=sum(map(len, events.values())), **totals)


def event_key(row):
    return tuple(row[key] for key in ("day", "action", "bucket", *EVENT_FIELDS))


def get_report(sessions, portfolio_id, code=None):
    with sessions() as session:
        if code:
            if not FUND_CODE.fullmatch(code):
                raise ValueError("Invalid SBI fund code")
            row = session.get(SbiRecord, (portfolio_id, "fund_history", code))
            return row.data if row else dict(code=code, events=[])
        rows = session.scalars(select(SbiRecord).where(
            SbiRecord.portfolio_id == portfolio_id, SbiRecord.kind == "fund_return",
        ).order_by(SbiRecord.id.desc()).limit(365)).all()
        history = [dict(as_of=row.data["as_of"], totals=row.data["totals"], holdings_observed_at=row.data.get("holdings_observed_at"),
                        funds=[{key: fund[key] for key in ("code", "bucket", "value", "return_jpy", "holdings")}
                               for fund in row.data["funds"]]) for row in reversed(rows)]
        latest = rows[0].data if rows else None
        return dict(latest=latest, history=history)
