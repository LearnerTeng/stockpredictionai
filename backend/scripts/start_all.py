"""管理本次启动创建的子进程。
Supervise the child processes created by this invocation.
"""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_status import read_state, state_dir, timestamp, write_state


@dataclass
class Service:
    command: list
    port: int | None = None
    process: subprocess.Popen | None = None
    failures: int = 0
    started: float = 0
    retry_at: float = 0
    run: str = ""
    last_success: str | None = None
    exit_code: int | None = None
    error: str | None = None

    def tick(self, name, root, directory, clock):
        if self.process is not None and self.process.poll() is not None:
            self.exit_code = self.process.returncode
            self.process = None
            if clock - self.started >= 300:
                self.failures = 0
            self.backoff(clock)
            self.error = f"Process exited ({self.exit_code})"
        if self.process is None and clock >= self.retry_at:
            self.run = uuid4().hex
            env = {**os.environ, "STOCKAI_WORKER_RUN": self.run, "STOCKAI_WORKER_NAME": name,
                   "STOCKAI_RUNTIME_DIR": str(directory)}
            try:
                with (directory / f"{name}.log").open("ab") as output:
                    self.process = subprocess.Popen(self.command, cwd=root, env=env, stdout=output,
                        stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
                self.started = clock
                self.error = None
            except OSError as error:
                self.error = type(error).__name__
                self.backoff(clock)

        health = read_state(directory / f"{name}.json")
        if health.get("run") == self.run and self.process:
            self.last_success = health.get("last_success") or self.last_success
        else:
            health = {}
        ready = False
        if self.port and self.process:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=.2):
                    ready = True
                    self.last_success = timestamp()
            except OSError:
                pass
        if self.process is None:
            status = "backoff"
        elif health.get("error"):
            status = "degraded"
        elif ready or health.get("heartbeat_at"):
            status = "running"
        else:
            status = "starting"
        return dict(status=status, pid=self.process.pid if self.process else None,
            last_success=self.last_success, exit_code=self.exit_code,
            failures=self.failures, retry_in_seconds=max(0, int(self.retry_at - clock)),
            error=health.get("error") or self.error, heartbeat_at=health.get("heartbeat_at"),
            last_ingestion=health.get("last_ingestion"), ingestion_in_progress=bool(health.get("ingestion_in_progress")))

    def backoff(self, clock):
        self.failures += 1
        self.retry_at = clock + min(300, 2 ** min(self.failures, 9))

    def request_stop(self):
        if self.process and self.process.poll() is None:
            try:
                if os.name == "nt":
                    self.process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.process.terminate()
            except OSError:
                pass

    def finish(self, timeout):
        child = self.process
        if child is None:
            return
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, timeout=10)
            else:
                child.kill()
            child.wait(timeout=10)


def supervise(root, services, directory, run=None):
    directory.mkdir(parents=True, exist_ok=True)
    run = run or uuid4().hex
    status_file = directory / "launcher.json"
    states = {}
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signals = (signal.SIGTERM, signal.SIGINT)
    previous = {sig: signal.signal(sig, stop) for sig in signals}
    try:
        print("Open http://127.0.0.1:5173. Ctrl+C stops this session.", flush=True)
        while not stopping and read_state(directory / "stop.json").get("run") != run:
            clock = time.monotonic()
            states = {name: service.tick(name, root, directory, clock) for name, service in services.items()}
            write_state(status_file, dict(status="running", run=run, pid=os.getpid(),
                                          updated_at=timestamp(), services=states))
            time.sleep(1)
    finally:
        for service in services.values():
            service.request_stop()
        deadline = time.monotonic() + 10
        for service in services.values():
            service.finish(max(0, deadline - time.monotonic()))
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        states = {name: {**state, "status": "stopped", "pid": None} for name, state in states.items()}
        write_state(status_file, dict(status="stopped", run=run, updated_at=timestamp(), services=states))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop", action="store_true", help="Request normal shutdown of this workspace's launcher")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    from database.session import create_database_engine
    directory = state_dir().resolve()
    if args.stop:
        current = read_state(directory / "launcher.json")
        if current.get("status") in ("starting", "running"):
            write_state(directory / "stop.json", {"run": current["run"]})
        return 0

    directory.mkdir(parents=True, exist_ok=True)
    with launcher_lock(directory):
        run = uuid4().hex
        status_file = directory / "launcher.json"
        write_state(status_file, dict(status="starting", run=run, pid=os.getpid(), updated_at=timestamp(), services={}))

        def stop_requested():
            return read_state(directory / "stop.json").get("run") == run

        from scripts.windows_dependencies import StartupStopped, connect_with_dependencies
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError

        try:
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "backend/alembic"))
            head = ScriptDirectory.from_config(config).get_current_head()
            engine = create_database_engine(connect_args={"connect_timeout": 4})
            try:
                with connect_with_dependencies(root, engine, stop_requested) as conn:
                    if stop_requested():
                        raise StartupStopped()
                    # 使用数据库会话锁，限制同一数据库只有一个启动器。
                    # Use a database session lock to allow one launcher per database.
                    if not conn.scalar(text("SELECT pg_try_advisory_lock(73410594)")):
                        raise RuntimeError("A launcher already manages this database")
                    version = conn.execute(text("SELECT to_regclass('alembic_version')")).scalar()
                    if version is None or conn.execute(text("SELECT version_num FROM alembic_version")).scalar() != head:
                        raise RuntimeError("Run python -m alembic upgrade head before starting")
                    conn.commit()
                    services = build_services(root)
                    supervise(root, services, directory, run=run)
            finally:
                engine.dispose()
        except (StartupStopped, KeyboardInterrupt):
            print("[startup] Stop requested while waiting for dependencies.", flush=True)
        except OperationalError:
            raise RuntimeError("Lost the PostgreSQL connection during startup. Check docker compose ps postgres.") from None
        finally:
            if read_state(status_file).get("status") == "starting":
                write_state(status_file, dict(status="stopped", run=run, updated_at=timestamp(), services={}))
    return 0


@contextmanager
def launcher_lock(directory):
    # 数据库锁可用前，用固定锁文件保护本次启动和停止状态。
    # Use a stable lock file to protect this run's startup and stop state before the database lock is available.
    with (directory / "launcher.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("A launcher already manages this workspace") from None
        else:
            import fcntl
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("A launcher already manages this workspace") from None
        yield


def build_services(root):
    for port in (8000, 8001, 5173):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                raise RuntimeError(f"Port {port} is already in use") from None
    node = shutil.which("node")
    if not node or not (root / "node_modules/vite/bin/vite.js").exists():
        raise RuntimeError("Install Node.js and run npm ci")
    python = sys.executable
    return {
        "api": Service([python, "backend/app.py"], 8000),
        "news": Service([python, "backend/scripts/news_worker.py"]),
        "research": Service([python, "backend/scripts/research_worker.py", "--news-only", "--interval", "60"]),
        "advice-scheduler": Service([python, "backend/scripts/advice_worker.py", "--scheduler"]),
        "advice": Service([python, "backend/scripts/advice_worker.py"]),
        "sbi": Service([python, "backend/scripts/sbi_worker.py"]),
        "image": Service([python, "-m", "uvicorn", "backend.image_service.main:app", "--host", "127.0.0.1", "--port", "8001"], 8001),
        "frontend": Service([node, "node_modules/vite/bin/vite.js", "--strictPort"], 5173),
    }


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"Startup failed: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
