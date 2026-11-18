"""供启动器、后台进程和状态 API 共用的运行状态。
Runtime status shared by the launcher, workers and status API.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

DEFAULT_DIR = Path(__file__).resolve().parent / "local_data" / "supervisor"


def state_dir():
    value = os.environ.get("STOCKAI_RUNTIME_DIR")
    return Path(value) if value else DEFAULT_DIR


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def read_state(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def heartbeat(*, success, error=None, **details):
    name = os.getenv("STOCKAI_WORKER_NAME")
    run = os.getenv("STOCKAI_WORKER_RUN")
    if not name or not run:
        return
    path = state_dir() / f"{name}.json"
    previous = read_state(path)
    write_state(path, dict(run=run, heartbeat_at=timestamp(),
        last_success=timestamp() if success else previous.get("last_success"),
        error=error, **details))


def launcher_status():
    current = read_state(state_dir() / "launcher.json")
    if current.get("status") == "running":
        if datetime.now(timezone.utc) - datetime.fromisoformat(current["updated_at"]) > timedelta(seconds=20):
            current["status"] = "unresponsive"
    return current or {"status": "stopped", "services": {}}
