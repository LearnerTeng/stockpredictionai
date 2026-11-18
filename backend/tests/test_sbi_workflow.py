from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from sqlalchemy.schema import CreateSchema, DropSchema
from database.models import Base, NewsItem, Portfolio, Position, ResearchDocument, SbiRecord
from database.session import session_factory
from database.trading_store import SqlAlchemyTradingStore
from scripts import sbi_worker
from trading.sbi import SbiImport

FIXTURES = Path(__file__).parent / "fixtures" / "sbi"
AT = datetime(2026, 11, 13, 11, tzinfo=timezone.utc)


class FakeMailer:
    configured = True

    def __init__(self):
        self.messages = []

    def send(self, recipients, subject, message):
        self.messages.append((recipients, subject, message))


class SbiWorkflowTests(TestCase):
    postgres = False

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name)
        self.root = path / "import"
        self.folder = self.root / "nisa"
        for directory in ("trades", "nav"):
            (self.folder / directory).mkdir(parents=True)
        (self.folder / "config.json").write_text(json.dumps(dict(snapshot_through="2026-11-10",
            funds=[dict(sbi_name="合成インデックス投信", sbi_bucket="NISA（成長）",
                        symbol="SYNTH-FUND", position_bucket="growth")])), encoding="utf-8")
        self.trading = SqlAlchemyTradingStore(os.environ["TEST_POSTGRES_URL"] if self.postgres else
                                              f"sqlite:///{path / 'db.sqlite'}")
        self.engine = self.trading.engine
        self.addCleanup(self.engine.dispose)
        if self.postgres:
            schema = "sbi_test_" + uuid4().hex
            with self.engine.begin() as conn:
                conn.execute(CreateSchema(schema))
            self.engine = self.engine.execution_options(schema_translate_map={None: schema})
            self.trading.sessions = session_factory(self.engine)
            def cleanup_schema():
                with self.engine.begin() as conn:
                    conn.execute(DropSchema(schema, cascade=True))
            self.addCleanup(cleanup_schema)
        Base.metadata.create_all(self.engine)
        seed = AT - timedelta(days=3)
        with self.trading.sessions.begin() as session:
            for pid in ("nisa", "second"):
                session.add(Portfolio(id=pid, name=pid, mode="read_only", currency="JPY", account_type="nisa",
                                      cash=0, benchmark_symbol="", created_at=seed, updated_at=seed))
                session.flush()
                session.add(Position(portfolio_id=pid, symbol="SYNTH-FUND", name="合成インデックス投信",
                    currency="JPY", account_bucket="growth", price_scale=10000, quantity=20000, average_cost=10000,
                    last_price=10000, reported_market_value=20000, reported_cost_basis=20000, source="snapshot", updated_at=seed))
            data = json.loads((FIXTURES / "news.json").read_text(encoding="utf-8-sig"))
            published, available = (datetime.fromisoformat(data[key]) for key in ("published_at", "available_at"))
            for key, stamp in (("early", available), ("future", AT + timedelta(hours=1))):
                session.add(NewsItem(id=key, title=data["title"], source="fixture", published_at=published, fetched_at=stamp))
                session.flush()
                session.add(ResearchDocument(id=key, article_id=key, revision=1, checksum=key,
                    title=data["title"] if key == "early" else "Future document", body=data["body"], url=data["url"],
                    source="fixture", symbols=["SYNTH-FUND"], published_at=published, available_at=stamp))
        self.mailer = FakeMailer()
        self.service = SbiImport(self.trading.sessions, self.mailer)

    def cycle(self):
        with patch.dict(os.environ, {"SBI_IMPORT_DIR": str(self.root), "SBI_ALERT_RECIPIENTS": "fixture@example.invalid"}), \
             patch.object(sys, "argv", ["sbi_worker.py", "--once"]), \
             patch.object(sbi_worker, "create_database_engine", return_value=self.engine), \
             patch("trading.sbi.SmtpMailer", return_value=self.mailer), \
             patch("trading.sbi.datetime", wraps=datetime) as clock:
            clock.now.return_value = AT
            self.assertEqual(sbi_worker.main(), 0)

    def client(self):
        import app
        stack = patch.multiple(app, trading_store=self.trading, _require_sentiment=lambda: (self.trading, None))
        stack.start()
        self.addCleanup(stack.stop)
        return app.app.test_client()

    def test_export_to_nav_alert_restart_and_web_reconciliation(self):
        # 这份 CP932 导出包含两笔完全相同的成交和一笔快照前的成交。
        # This CP932 export contains two identical fills and one pre-snapshot execution.
        data = (FIXTURES / "executions.csv").read_text(encoding="utf-8-sig")
        export = self.folder / "trades" / "original.csv"
        export.write_bytes(data.encode("cp932"))
        shutil.copy(FIXTURES / "nav-before.csv", self.folder / "nav")
        self.cycle()
        client = self.client()
        self.assertEqual(client.get("/portfolio?id=nisa").json["positions"][0]["quantity"], 30000)
        self.assertEqual(client.get("/portfolio/performance?id=nisa").json["points"], [])
        self.assertEqual(client.get("/portfolio?id=second").json["positions"][0]["quantity"], 20000)
        shutil.copy(export, export.with_name("renamed.csv"))
        self.cycle()
        self.assertEqual(client.get("/portfolio?id=nisa").json["positions"][0]["quantity"], 30000)

        shutil.copy(FIXTURES / "nav-after.csv", self.folder / "nav")
        self.cycle()
        portfolio = client.get("/portfolio?id=nisa").json
        self.assertEqual(portfolio["positions"][0]["quantity"], 30000)
        self.assertEqual(portfolio["market_value"], 27900)
        self.assertEqual(portfolio["unrealized_pnl"], -2100)
        self.assertEqual(len(self.mailer.messages), 1)
        self.assertIn("Synthetic fund publishes an update", self.mailer.messages[0][2])
        self.assertNotIn("Future document", self.mailer.messages[0][2])
        self.cycle()
        self.assertEqual(len(self.mailer.messages), 1)
        self.assertEqual(client.get("/portfolio/sbi?id=nisa").json["alerts"][0]["delivery"], "sent")

        # 新导出中有三笔相同的成交，显式核对新增的一笔。
        # A different export contains three identical fills. Explicitly reconcile the additional fill.
        export.with_name("wider.csv").write_text(data + data.splitlines()[-1] + "\n", encoding="utf-8")
        self.cycle()
        status = client.get("/portfolio/sbi?id=nisa").json
        review = next(file for file in status["files"] if file["status"] == "needs_review")
        self.assertEqual(review["overlaps"][0]["existing"], 2)
        self.assertEqual(review["overlaps"][0]["exported"], 3)
        self.assertEqual(client.get("/portfolio?id=nisa").json["positions"][0]["quantity"], 30000)
        self.assertEqual(client.post("/portfolio/sbi?id=nisa", json=dict(id=review["id"],
            fingerprint=review["fingerprint"], additions={review["overlaps"][0]["key"]: 1})).status_code, 202)
        self.cycle()
        self.assertEqual(client.get("/portfolio?id=nisa").json["positions"][0]["quantity"], 35000)
        self.assertEqual(len(self.mailer.messages), 1)

    def test_reject_malformed_file_without_partial_write(self):
        data = (FIXTURES / "executions.csv").read_text(encoding="utf-8-sig")
        (self.folder / "trades" / "bad.csv").write_text(data + data.splitlines()[-1].replace(
            "投信金額買付", "外国投信買付") + "\n", encoding="utf-8")
        self.cycle()
        self.assertEqual(self.trading.get_portfolio("nisa")["positions"][0]["quantity"], 20000)
        status = self.service.status("nisa")
        self.assertTrue(any(item["status"] == "rejected" and "unsupported transaction" in item["error"] for item in status["files"]))
        with self.trading.sessions() as session:
            self.assertFalse(session.scalars(select(SbiRecord).where(SbiRecord.kind == "trade")).all())

    def test_interrupted_delivery_stays_unknown(self):
        with self.trading.sessions.begin() as session:
            session.add(SbiRecord(portfolio_id="nisa", kind="alert", id="interrupt",
                data={"delivery": "sending"}, updated_at=AT - timedelta(minutes=10)))
        self.service.deliver("nisa", AT, ("fixture@example.invalid",))
        self.assertFalse(self.mailer.messages)
        self.assertEqual(self.service.status("nisa")["alerts"][0]["delivery"], "unknown")


@skipUnless(os.getenv("TEST_POSTGRES_URL"), "set TEST_POSTGRES_URL for isolated SBI integration")
class PostgresSbiWorkflowTests(SbiWorkflowTests):
    postgres = True
