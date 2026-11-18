"""将已核对的 SBI 基金成交和带日期的日元净值导入只读组合。
Import verified SBI fund executions and dated JPY NAVs into read-only portfolios.
"""
from collections import defaultdict
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import re

from sqlalchemy import cast, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import aliased

from database.models import Portfolio, Position, ResearchDocument, SbiRecord
from market_data.calendar import latest_completed_session
from market_data.point_in_time import aware, utc
from sentiment.mailer import SmtpMailer

JST = timezone(timedelta(hours=9))
SCALE = 10_000
MAX_FILE_BYTES = 5_000_000
BUY = {"投信口数買付", "投信金額買付", "分配金再投資"}
SELL = {"投信口数解約", "投信金額解約", "投信口数買取", "投信金額買取"}
TRADE_FIELDS = {"約定日", "ファンド名", "預り区分", "取引種別", "約定数量", "約定単価", "受渡日", "受渡金額"}
NAV_FIELDS = {"symbol", "nav_date", "available_at", "jpy_per_10000"}


class AmbiguousExport(ValueError):
    def __init__(self, overlaps):
        self.overlaps = overlaps


class ImportWaiting(ValueError):
    """依赖文件可能在后续扫描中出现。
    A dependency file can arrive in a later scan.
    """


def csv_rows(raw, required):
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = raw.decode("cp932")
    reader = csv.DictReader(StringIO(decoded, newline=""), strict=True)
    headers = [key.strip() for key in reader.fieldnames or []]
    if not required <= set(headers) or len(headers) != len(set(headers)):
        raise ValueError("Check CSV headers; required: " + ", ".join(sorted(required)))
    reader.fieldnames = headers
    for row in reader:
        if None in row or any(row[key] is None for key in required):
            raise ValueError(f"CSV line {reader.line_num}: check column count and quoted thousands separators")
        yield reader.line_num, {key: row[key].strip() for key in required}


def number(value):
    if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,6})?", value):
        raise ValueError("expected a positive number without unit suffixes")
    result = Decimal(value.replace(",", ""))
    if not 0 < result <= 10**14:
        raise ValueError("number out of range")
    return format(result.normalize(), "f")


def import_rows(raw, kind, funds, cutoff, now):
    required = TRADE_FIELDS if kind == "trade" else NAV_FIELDS
    found = {}
    counts = defaultdict(int)
    for line, row in csv_rows(raw, required):
        try:
            if kind == "trade":
                day = date.fromisoformat(row["約定日"].replace("/", "-"))
                if day > now.astimezone(JST).date():
                    raise ValueError("future execution date")
                if day <= cutoff:
                    continue
                symbol = funds.get((row["ファンド名"], row["預り区分"]))
                if not symbol:
                    raise ValueError("map the exact fund name and SBI account bucket in config.json")
                side = row["取引種別"]
                if side not in BUY | SELL:
                    raise ValueError("unsupported transaction type; reconcile against the SBI transaction report")
                quantity = number(row["約定数量"])
                if Decimal(quantity) % 1:
                    raise ValueError("domestic fund units must be whole 口")
                settled = date.fromisoformat(row["受渡日"].replace("/", "-"))
                if settled < day:
                    raise ValueError("settlement date precedes execution date")
                data = dict(symbol=symbol, day=day.isoformat(), side="buy" if side in BUY else "sell",
                            transaction=side,
                            quantity=quantity, amount=number(row["受渡金額"]),
                            price=number(row["約定単価"]), settlement=settled.isoformat())
                key = sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
                counts[key] += 1
            else:
                symbol = row["symbol"]
                if symbol not in funds.values():
                    raise ValueError("NAV symbol must match a position symbol in config.json")
                day = date.fromisoformat(row["nav_date"])
                available = aware(row["available_at"])
                if available.astimezone(JST).date() < day:
                    raise ValueError("NAV availability precedes its valuation date")
                if available > now:
                    raise ImportWaiting("NAV is not available yet; check available_at")
                key = f"{symbol}:{day.isoformat()}"
                data = dict(symbol=symbol, day=day.isoformat(), available_at=available.isoformat(),
                            nav=number(row["jpy_per_10000"]))
            if key in found and found[key] != data:
                raise ValueError("the same execution ID or NAV date has conflicting values")
            found[key] = data
        except ImportWaiting:
            raise
        except (ValueError, InvalidOperation) as error:
            raise ValueError(f"CSV line {line}: {error}") from None
    return found, counts


def read_config(directory):
    config = json.loads((directory / "config.json").read_text(encoding="utf-8-sig"))
    cutoff = date.fromisoformat(config["snapshot_through"])
    confirmed = date.fromisoformat(config.get("holdings_confirmed_through", cutoff.isoformat()))
    if confirmed < cutoff:
        raise ValueError("holdings_confirmed_through cannot precede snapshot_through")
    drop = Decimal(str(config.get("nav_drop_pct", 5)))
    if not drop.is_finite() or not 0 < drop <= 100:
        raise ValueError("nav_drop_pct must be greater than zero and at most 100")
    funds = {}
    for fund in config["funds"]:
        key = (fund["sbi_name"], fund["sbi_bucket"])
        symbol, bucket = fund["symbol"], fund["position_bucket"]
        if not re.fullmatch(r"[A-Z0-9_.-]{1,32}", symbol) or not re.fullmatch(r"[a-z0-9_-]{1,32}", bucket):
            raise ValueError("invalid position symbol or bucket")
        if not all(isinstance(value, str) and value and len(value) <= 255 for value in key):
            raise ValueError("supply exact SBI fund name and bucket")
        if key in funds or symbol in (item["symbol"] for item in funds.values()):
            raise ValueError("each fund/bucket requires a distinct portfolio position symbol")
        news = fund.get("news_symbols", [symbol])
        if (not isinstance(news, list) or len(news) > 8
                or any(not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9_.^=-]{1,32}", value) for value in news)):
            raise ValueError("news_symbols must be a list of up to eight market symbols")
        funds[key] = {**fund, "news_symbols": sorted(set(news))}
    if not funds:
        raise ValueError("at least one fund mapping is required")
    return cutoff, confirmed, funds, drop


def configured_root():
    value = os.getenv("SBI_IMPORT_DIR", "").strip()
    return Path(value).expanduser() if value else None


class SbiImport:
    def __init__(self, sessions, mailer=None):
        self.sessions = sessions
        self.mailer = mailer if mailer is not None else SmtpMailer()

    def _lock(self, session, portfolio_id):
        if session.bind.dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        portfolio = session.get(Portfolio, portfolio_id, with_for_update=True)
        if not portfolio or (portfolio.account_type, portfolio.currency, portfolio.mode) != ("nisa", "JPY", "read_only"):
            raise ValueError("SBI import requires an existing read_only JPY NISA portfolio")
        return portfolio

    @staticmethod
    def _rows(session, portfolio_id, kind):
        return session.scalars(select(SbiRecord).where(
            SbiRecord.portfolio_id == portfolio_id, SbiRecord.kind == kind)).all()

    @staticmethod
    def _record(session, portfolio_id, kind, key, data, now):
        session.merge(SbiRecord(portfolio_id=portfolio_id, kind=kind, id=key, data=data, updated_at=now))

    def scan(self, root, now=None, recipients=()):
        now = now or datetime.now(timezone.utc)
        with self.sessions() as session:
            portfolios = session.scalars(select(Portfolio.id).where(
                Portfolio.account_type == "nisa", Portfolio.currency == "JPY", Portfolio.mode == "read_only")).all()
        if not root.is_dir():
            raise ValueError("SBI_IMPORT_DIR must point to an existing folder")
        for portfolio_id in portfolios:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", portfolio_id):
                continue
            folder = root / portfolio_id
            if folder.is_dir():
                self._scan_account(folder, portfolio_id, now)
            self.deliver(portfolio_id, now, recipients)

    def _scan_account(self, folder, portfolio_id, now):
        try:
            cutoff, confirmed, funds, drop = read_config(folder)
            if confirmed > now.astimezone(JST).date():
                raise ValueError("snapshot_through and holdings_confirmed_through cannot be in the future")
            with self.sessions.begin() as session:
                self._lock(session, portfolio_id)
                known = session.get(SbiRecord, (portfolio_id, "config", "snapshot"))
                if known and known.data["through"] != cutoff.isoformat():
                    raise ValueError("snapshot_through is locked after the initial baseline; restore the original cutoff")
                current = {row.symbol: row for row in session.scalars(select(Position).where(
                    Position.portfolio_id == portfolio_id))}
                expected = {f["symbol"] for f in funds.values()}
                if set(current) - expected:
                    raise ValueError("map all existing positions before importing")
                saved = {row.id: row.data for row in self._rows(session, portfolio_id, "seed")}
                if set(saved) - expected:
                    raise ValueError("remove no fund mappings after they have been initialized")
                for key, fund in funds.items():
                    symbol = fund["symbol"]
                    row = current.get(symbol)
                    if row and (row.account_bucket != fund["position_bucket"] or row.currency != "JPY" or row.price_scale != SCALE):
                        raise ValueError("fund mapping must match snapshot position bucket, JPY and 10,000-unit scale")
                    mapping = dict(name=key[0], sbi_bucket=key[1], bucket=fund["position_bucket"])
                    if symbol in saved:
                        if any(saved[symbol][field] != value for field, value in mapping.items()):
                            raise ValueError("initialized fund mappings are immutable")
                        if saved[symbol].get("news_symbols") != fund["news_symbols"]:
                            self._record(session, portfolio_id, "seed", symbol,
                                         {**saved[symbol], "news_symbols": fund["news_symbols"]}, now)
                        continue
                    seed = dict(mapping, news_symbols=fund["news_symbols"], quantity="0", cost="0", nav=None)
                    if row:
                        quantity = Decimal(str(row.quantity))
                        cost = (Decimal(str(row.reported_cost_basis)) if row.reported_cost_basis is not None
                                else quantity * Decimal(str(row.average_cost)) / SCALE)
                        seed.update(quantity=str(quantity), cost=str(cost), nav=str(row.last_price))
                    self._record(session, portfolio_id, "seed", symbol, seed, now)
                metadata = {"through": cutoff.isoformat(), "confirmed_through": confirmed.isoformat()}
                if not known or known.data != metadata:
                    self._record(session, portfolio_id, "config", "snapshot", metadata, now)
                self._record(session, portfolio_id, "file", "config", {"file": "config.json", "status": "ready"}, now)
        except (KeyError, TypeError, ValueError, OSError, InvalidOperation) as error:
            self._file_status(portfolio_id, "config", "config.json", "rejected", now, str(error))
            return

        mapped = {key: value["symbol"] for key, value in funds.items()}
        for kind in ("nav", "trade"):
            for path in sorted((folder / ("trades" if kind == "trade" else "nav")).glob("*.csv")):
                file_id = sha256(f"{kind}/{path.name}".encode()).hexdigest()
                content = None
                try:
                    with path.open("rb") as handle:
                        raw = handle.read(MAX_FILE_BYTES + 1)
                    if len(raw) > MAX_FILE_BYTES:
                        raise ValueError("CSV exceeds 5 MB; split it into smaller exports")
                    content = sha256(raw).hexdigest()
                    with self.sessions.begin() as session:
                        portfolio = self._lock(session, portfolio_id)
                        previous = session.get(SbiRecord, (portfolio_id, "file", file_id))
                        if previous and previous.data.get("hash") == content and previous.data["status"] == "imported":
                            continue
                        fingerprint = kind + ":" + content
                        duplicate = session.get(SbiRecord, (portfolio_id, "imported", fingerprint))
                        if duplicate:
                            self._record(session, portfolio_id, "file", file_id,
                                         {"file": path.name, "status": "imported", "hash": content, "rows": 0}, now)
                            continue
                        rows, counts = import_rows(raw, kind, mapped, cutoff, now)
                        if kind == "trade":
                            rows = self._match_trades(session, portfolio_id, rows, counts, content)
                        changed = set()
                        for key, data in rows.items():
                            existing = session.get(SbiRecord, (portfolio_id, kind, key))
                            if existing:
                                if existing.data != data:
                                    raise ValueError("conflicting execution ID or NAV date; reconcile with the original file")
                                continue
                            self._record(session, portfolio_id, kind, key, data, now)
                            changed.add(data["symbol"])
                        session.flush()
                        if changed:
                            self._project(session, portfolio, changed, cutoff, drop, now)
                        self._record(session, portfolio_id, "file", file_id,
                                     {"file": path.name, "status": "imported", "hash": content, "rows": len(rows)}, now)
                        self._record(session, portfolio_id, "imported", fingerprint, {}, now)
                except AmbiguousExport as error:
                    self._file_status(portfolio_id, file_id, path.name, "needs_review", now,
                                      "Matching rows occur in an earlier export. Check whether the exports overlap.",
                                      fingerprint=content, overlaps=error.overlaps)
                except (ImportWaiting, OSError) as error:
                    self._file_status(portfolio_id, file_id, path.name, "retry", now, str(error))
                except (ValueError, csv.Error) as error:
                    self._file_status(portfolio_id, file_id, path.name, "rejected", now, str(error))

    def _match_trades(self, session, portfolio_id, rows, counts, content):
        existing = defaultdict(int)
        for row in self._rows(session, portfolio_id, "trade"):
            existing[row.id.partition(":")[0]] += 1
        review = session.get(SbiRecord, (portfolio_id, "resolution", content))
        overlaps = [dict(key=key, symbol=rows[key]["symbol"], date=rows[key]["day"], side=rows[key]["side"],
                         units=rows[key]["quantity"], settlement_jpy=rows[key]["amount"],
                         existing=existing[key], exported=count)
                    for key, count in counts.items() if existing[key]]
        expected = {item["key"]: item["existing"] for item in overlaps}
        if overlaps and (not review or review.data["known"] != expected):
            raise AmbiguousExport(overlaps)
        matched = {}
        for key, count in counts.items():
            known = existing[key]
            added = review.data["additions"][key] if known else count
            end = known + added
            for occurrence in range(known + 1, end + 1):
                matched[f"{key}:{occurrence}"] = rows[key]
        return matched

    def resolve(self, portfolio_id, file_id, fingerprint, additions):
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            self._lock(session, portfolio_id)
            row = session.get(SbiRecord, (portfolio_id, "file", file_id))
            if not row or row.data["status"] != "needs_review" or row.data["fingerprint"] != fingerprint:
                raise ValueError("This file review changed; refresh and check the current file")
            items = row.data["overlaps"]
            known = {item["key"]: item["existing"] for item in items}
            if not isinstance(additions, dict) or set(additions) != set(known):
                raise ValueError("Provide a new execution count for each matching group")
            for item in items:
                count = additions[item["key"]]
                if type(count) is not int or not max(0, item["exported"] - item["existing"]) <= count <= item["exported"]:
                    raise ValueError("New execution counts must account for all exported rows")
            self._record(session, portfolio_id, "resolution", fingerprint, dict(known=known, additions=additions), now)
            row.data = {**row.data, "status": "retry", "error": "Decision recorded; waiting for the next import scan"}
            row.updated_at = now

    def _file_status(self, portfolio_id, key, filename, status, now, error, **details):
        with self.sessions.begin() as session:
            self._lock(session, portfolio_id)
            data = {"file": filename, "status": status, "error": error, **details}
            previous = session.get(SbiRecord, (portfolio_id, "file", key))
            if not previous or previous.data != data:
                self._record(session, portfolio_id, "file", key, data, now)

    def _project(self, session, portfolio, changed, cutoff, drop, now):
        trades, navs = defaultdict(list), defaultdict(list)
        for row in self._rows(session, portfolio.id, "trade"):
            trades[row.data["symbol"]].append((row.data["day"], row.id, row.data))
        for row in self._rows(session, portfolio.id, "nav"):
            navs[row.data["symbol"]].append((row.data["day"], row.data))
        positions = {row.symbol: row for row in session.scalars(select(Position).where(Position.portfolio_id == portfolio.id))}
        for symbol in sorted(changed):
            seed = session.get(SbiRecord, (portfolio.id, "seed", symbol)).data
            quantity, cost = Decimal(seed["quantity"]), Decimal(seed["cost"])
            sides = defaultdict(set)
            for day, _, trade in sorted(trades[symbol]):
                sides[day].add(trade["side"])
                if len(sides[day]) > 1:
                    raise ValueError("same-day buys and sells need verified execution ordering; reconcile the snapshot")
                units = Decimal(trade["quantity"])
                if trade["side"] == "buy":
                    quantity += units
                    cost += Decimal(trade["amount"])
                else:
                    if units > quantity:
                        raise ImportWaiting("sale exceeds units; import missing earlier buys or correct the execution")
                    cost *= (quantity - units) / quantity
                    quantity -= units
            prices = [data for day, data in sorted(navs[symbol]) if day >= cutoff.isoformat()]
            position = positions.get(symbol)
            if quantity == 0:
                if position:
                    session.delete(position)
                    portfolio.updated_at = now
                continue
            if not prices and seed["nav"] is None:
                raise ImportWaiting("import a dated NAV first for a new fund")
            price = Decimal(prices[-1]["nav"] if prices else seed["nav"])
            if not position:
                position = Position(portfolio_id=portfolio.id, symbol=symbol, name=seed["name"], currency="JPY",
                                    price_scale=SCALE, account_bucket=seed["bucket"])
                session.add(position)
            position.quantity = float(quantity)
            position.average_cost = float(cost * SCALE / quantity)
            position.reported_cost_basis = float(cost)
            if prices or trades[symbol]:
                position.reported_market_value = None
            position.last_price, position.updated_at, position.source = float(price), now, "sbi-import"
            portfolio.updated_at = now
            if prices:
                self._record(session, portfolio.id, "valuation", symbol, prices[-1], now)
            recent_day = latest_completed_session(now - timedelta(days=1), "JP").isoformat()
            if len(prices) >= 2 and prices[-1]["day"] >= recent_day:
                previous = Decimal(prices[-2]["nav"])
                change = (price - previous) / previous * 100
                if change <= -drop:
                    self._alert(session, portfolio.id, symbol, seed["news_symbols"], prices[-1], change, now)

    def _alert(self, session, portfolio_id, symbol, news_symbols, nav, change, now):
        key = f"{symbol}:{nav['day']}:nav-drop"
        if session.get(SbiRecord, (portfolio_id, "alert", key)):
            return
        newer = aliased(ResearchDocument)
        query = select(ResearchDocument).where(
            ResearchDocument.available_at.between(now - timedelta(days=7), now),
            ResearchDocument.published_at <= now,
            ~select(newer.id).where(newer.article_id == ResearchDocument.article_id,
                newer.revision > ResearchDocument.revision, newer.available_at <= now).exists(),
        )
        if news_symbols and session.bind.dialect.name == "postgresql":
            query = query.where(or_(*(cast(ResearchDocument.symbols, JSONB).contains([item]) for item in news_symbols)))
        docs = session.scalars(query.order_by(ResearchDocument.available_at.desc(), ResearchDocument.id).limit(200)) if news_symbols else []
        news = [{"title": doc.title, "url": doc.url, "available_at": utc(doc.available_at).isoformat(),
                 "symbols": sorted(set(news_symbols).intersection(doc.symbols))}
                for doc in docs if set(news_symbols).intersection(doc.symbols)][:5]
        self._record(session, portfolio_id, "alert", key, dict(
            symbol=symbol, nav_date=nav["day"], change_pct=round(float(change), 4),
            news=news, delivery="pending", detected_at=now.isoformat()), now)

    def deliver(self, portfolio_id, now, recipients):
        # 调用 SMTP 前提交领取记录。发送中断或结果不明时需人工核对。
        # Commit the claim before SMTP. Interrupted sends or unknown delivery results require manual reconciliation.
        with self.sessions.begin() as session:
            self._lock(session, portfolio_id)
            for row in self._rows(session, portfolio_id, "alert"):
                if row.data["delivery"] == "sending" and utc(row.updated_at) < now - timedelta(minutes=5):
                    row.data = {**row.data, "delivery": "unknown", "error": "Interrupted during delivery; check mailbox"}
                    row.updated_at = now
        if not recipients or not self.mailer.configured:
            return
        while True:
            with self.sessions.begin() as session:
                self._lock(session, portfolio_id)
                row = next((item for item in self._rows(session, portfolio_id, "alert")
                            if item.data["delivery"] == "pending"), None)
                if row is None:
                    return
                key, data = row.id, row.data
                row.data = {**data, "delivery": "sending"}
                row.updated_at = datetime.now(timezone.utc)
            message = f"{data['symbol']}: NAV {data['change_pct']}% vs previous observation, {data['nav_date']}"
            error = None
            try:
                titles = "\n".join(f"{', '.join(doc.get('symbols', []))}: {doc['title']} {doc['url'] or ''}" for doc in data["news"])
                self.mailer.send(list(recipients), "SBI fund NAV alert", message + "\n\n" + titles)
            except Exception as exc:
                error = type(exc).__name__
            with self.sessions.begin() as session:
                self._lock(session, portfolio_id)
                row = session.get(SbiRecord, (portfolio_id, "alert", key))
                row.data = {**data, "delivery": "unknown" if error else "sent"}
                if error:
                    row.data = {**row.data, "error": error + "; check SMTP and mailbox before resending"}
                row.updated_at = datetime.now(timezone.utc)

    def status(self, portfolio_id):
        with self.sessions() as session:
            def recent(kind):
                return [dict(id=row.id, updated_at=utc(row.updated_at).isoformat(),
                             **{key: value for key, value in row.data.items() if key != "hash"})
                        for row in session.scalars(select(SbiRecord).where(
                            SbiRecord.portfolio_id == portfolio_id, SbiRecord.kind == kind,
                        ).order_by(SbiRecord.updated_at.desc(), SbiRecord.id).limit(30))]
            snapshot = session.get(SbiRecord, (portfolio_id, "config", "snapshot"))
            return dict(enabled=configured_root() is not None, files=recent("file"),
                        alerts=recent("alert"), valuations=recent("valuation"), snapshot=snapshot.data if snapshot else None)
