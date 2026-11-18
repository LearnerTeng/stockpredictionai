import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from unittest import TestCase, skipUnless
from urllib.error import URLError
from urllib.request import urlopen

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from database.models import Base, Instrument
from datetime import datetime, timezone
from sentiment.store import SentimentStore
from runtime_status import read_state, write_state


class LauncherRecoveryTests(TestCase):
    def test_news_crash_does_not_stop_portfolio_api_and_restart_drains_queue(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            store = SentimentStore(f"sqlite:///{folder / 'news.db'}")
            Base.metadata.create_all(store.engine)
            try:
                with store.sessions.begin() as session:
                    now = datetime.now(timezone.utc)
                    session.add(Instrument(symbol="AAPL", name="Apple", market="US", currency="USD",
                                           status="active", created_at=now, updated_at=now))
                job = store.create_job(["AAPL"], "incremental", ["US"])
            finally:
                store.engine.dispose()
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            (folder / "news_fixture.py").write_text("""
import os
from pathlib import Path
from time import monotonic, sleep
from urllib.request import urlopen
from urllib.error import URLError
from unittest.mock import patch
from scripts import news_worker
from sentiment.service import NewsIngestionService
from sentiment.store import SentimentStore

counter = Path(os.environ['RECOVERY_FIXTURE']) / 'crashed'
if not counter.exists():
    port = os.environ['RECOVERY_PORT']
    deadline = monotonic() + 15
    while monotonic() < deadline:
        try:
            with urlopen(f'http://127.0.0.1:{port}/portfolio', timeout=.4):
                break
        except URLError:
            sleep(.2)
    counter.touch()
    raise SystemExit(23)
os.environ['DATABASE_URL'] = os.environ['RECOVERY_DATABASE']
store = SentimentStore(os.environ['RECOVERY_DATABASE'])
def fixture_service(store):
    service = NewsIngestionService(store)
    service.providers = []
    return service
with patch.object(news_worker, 'SentimentStore', return_value=store), patch.object(news_worker, 'NewsIngestionService', side_effect=fixture_service):
    news_worker.main()
""", encoding="utf-8")
            (folder / "supervise_fixture.py").write_text("""
import os
from pathlib import Path
import sys
from scripts.start_all import Service, supervise
root = Path(os.environ['RECOVERY_FIXTURE'])
port = int(os.environ['RECOVERY_PORT'])
api = 'from app import app; app.run(host="127.0.0.1", port=' + str(port) + ')'
services = {
    "api": Service([sys.executable, "-c", api], port),
    "news": Service([sys.executable, str(root / "news_fixture.py"), "--poll-seconds", "5"]),
}
supervise(root, services, root)
""", encoding="utf-8")
            env = {**os.environ, "PYTHONPATH": str(BACKEND), "RECOVERY_FIXTURE": tmp,
                   "RECOVERY_DATABASE": f"sqlite:///{folder / 'news.db'}", "RECOVERY_PORT": str(port),
                   "DATABASE_URL": "", "TRADING_DB_PATH": str(folder / "trading.db"),
                   "STOCK_DATA_DB_PATH": str(folder / "market.db"), "STOCKAI_RUNTIME_DIR": str(folder)}
            launcher = subprocess.Popen([sys.executable, str(folder / "supervise_fixture.py")], env=env,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            state_path = folder / "launcher.json"
            try:
                deadline = monotonic() + 40
                api_pids = set()
                backoff = False
                during_backoff = False
                recovered = False
                while monotonic() < deadline:
                    states = read_state(state_path).get("services", {})
                    api, news = states.get("api", {}), states.get("news", {})
                    if api.get("pid"):
                        api_pids.add(api["pid"])
                    if news.get("status") == "backoff" and news.get("exit_code") == 23:
                        backoff = True
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/portfolio", timeout=.5) as result:
                            self.assertEqual(json.load(result)["id"], "primary")
                            if news.get("status") == "backoff":
                                during_backoff = True
                    except URLError:
                        if api.get("status") == "running":
                            raise
                    if backoff and news.get("last_success") and store.job(job["id"])["status"] == "completed":
                        recovered = True
                        break
                    sleep(.2)
                self.assertTrue(backoff)
                self.assertTrue(during_backoff)
                self.assertTrue(recovered, {file.name: file.read_text(errors="replace")[-2000:] for file in folder.glob("*.log")})
                self.assertEqual(len(api_pids), 1)
            finally:
                state = read_state(state_path)
                if state.get("run"):
                    write_state(folder / "stop.json", {"run": state["run"]})
                else:
                    launcher.terminate()
                try:
                    launcher.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    launcher.kill()
                    launcher.wait(timeout=5)
                store.engine.dispose()
            self.assertEqual(launcher.returncode, 0)
            self.assertEqual(read_state(state_path)["status"], "stopped")


class PostgresLauncherRecoveryTests(TestCase):
    @skipUnless(os.getenv("TEST_POSTGRES_URL"), "set TEST_POSTGRES_URL for news lease recovery")
    def test_news_job_recovers_as_soon_as_its_advisory_lock_is_released(self):
        from uuid import uuid4
        from sqlalchemy.schema import CreateSchema, DropSchema
        from database.session import session_factory

        store = SentimentStore(os.environ["TEST_POSTGRES_URL"])
        schema = "news_recovery_" + uuid4().hex
        try:
            with store.engine.begin() as connection:
                connection.execute(CreateSchema(schema))
            store.engine = store.engine.execution_options(schema_translate_map={None: schema})
            store.sessions = session_factory(store.engine)
            Base.metadata.create_all(store.engine)
            job = store.create_job(["AAPL"], "incremental", ["US"])
            with store.worker_lock() as acquired:
                self.assertTrue(acquired)
                store.update_job(job["id"], status="running", attempts=1)
                self.assertEqual(store.pending_jobs(), [])
                self.assertEqual(store.job(job["id"])["status"], "running")
            recovered = store.pending_jobs()
            self.assertEqual([(row["id"], row["status"]) for row in recovered], [(job["id"], "retrying")])
        finally:
            with store.engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True, if_exists=True))
            store.engine.dispose()
