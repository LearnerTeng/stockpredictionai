import csv
from datetime import date
from io import StringIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.models import Base, Portfolio
from database.session import create_database_engine, session_factory
from trading.sbi_returns import HISTORY_HEADER, RETURN_HEADER, get_report, save_report
from datetime import datetime, timezone


def encode(header, *rows):
    buffer = StringIO()
    csv.writer(buffer).writerows([header, *rows])
    return buffer.getvalue().encode("utf-8-sig")


class SbiReturnsTests(TestCase):
    def test_repeated_daily_import_event_multiplicity_and_rollback(self):
        with TemporaryDirectory() as directory:
            engine = create_database_engine(f"sqlite:///{Path(directory) / 'funds.db'}")
            try:
                self.exercise(engine)
            finally:
                engine.dispose()

    def exercise(self, engine):
        Base.metadata.create_all(engine)
        sessions = session_factory(engine)
        now = datetime.now(timezone.utc)
        with sessions.begin() as session:
            session.add(Portfolio(id="nisa", name="Fixture NISA", mode="read_only", account_type="nisa",
                                  currency="JPY", cash=0, benchmark_symbol="", created_at=now, updated_at=now))
        returns = encode(RETURN_HEADER, ["保有中", "Synthetic Fund", "NISA (成長)", "金額", 1100, 0, 0, 20, 1000, 0, 120, "12%"])
        event = ["2026/11/10", "買付", "NISA (成長)", "金額", 1000, 1000, 0, 0, 0, 10000, 1000, 1000, 10000]
        history = encode(HISTORY_HEADER, event, event)
        options = dict(names={"FIXTURE1": "Synthetic Fund"}, history={"FIXTURE1": history})
        first = date(2026, 11, 11)
        self.assertEqual(save_report(sessions, "nisa", first, returns, 120, **options)["events"], 2)
        self.assertIsNone(get_report(sessions, "nisa")["latest"])
        save_report(sessions, "nisa", first, returns, 120, apply=True, **options)
        save_report(sessions, "nisa", first, returns, 120, apply=True, **options)
        self.assertEqual(len(get_report(sessions, "nisa", "FIXTURE1")["events"]), 2)
        self.assertEqual(len(get_report(sessions, "nisa")["history"]), 1)
        second = date(2026, 11, 12)
        with self.assertRaisesRegex(ValueError, "CSV total"):
            save_report(sessions, "nisa", second, returns, 1, apply=True)
        with self.assertRaisesRegex(ValueError, "previously recorded"):
            save_report(sessions, "nisa", second, returns, 120, apply=True, names=options["names"],
                        history={"FIXTURE1": encode(HISTORY_HEADER, event)})
        self.assertEqual(len(get_report(sessions, "nisa")["history"]), 1)
        save_report(sessions, "nisa", second, returns, 120, apply=True)
        saved = get_report(sessions, "nisa")
        self.assertEqual([row["as_of"] for row in saved["history"]], ["2026-11-11", "2026-11-12"])
        self.assertEqual(saved["latest"]["totals"]["return_jpy"], 120)
