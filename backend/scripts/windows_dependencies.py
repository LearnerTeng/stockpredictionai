"""从 Windows 启动器启动现有的本地 Compose 数据库。
Start the existing local Compose database from the Windows launcher.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from sqlalchemy.exc import OperationalError


WINDOWS = os.name == "nt"
ENGINE_TIMEOUT = 120
DATABASE_TIMEOUT = 60
DESKTOP_CONTEXT = ("--context", "desktop-linux")
DATA_PATH = "/var/lib/postgresql/data"


class StartupStopped(Exception):
    pass


def log(message):
    print(f"[startup] {message}", flush=True)


def docker_cli(root, executable, *args):
    # 此工作区的 Compose 资源属于固定使用的 Docker Desktop 上下文。
    # This checkout's Compose resources belong to the pinned Docker Desktop context.
    environment = {key: value for key, value in os.environ.items()
                   if key not in ("DOCKER_HOST", "DOCKER_CONTEXT")}
    try:
        return subprocess.run([executable, *args], cwd=root, env=environment, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=8,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "Docker CLI timed out")


def wait_until(check, stop, seconds, interval=2):
    deadline = time.monotonic() + seconds
    while True:
        if stop():
            raise StartupStopped()
        result = check()
        if result:
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(interval, remaining))


def connect_if_ready(engine):
    try:
        return engine.connect()
    except OperationalError:
        return None


def connect_with_dependencies(root, engine, stop):
    if stop():
        raise StartupStopped()
    connection = connect_if_ready(engine)
    if connection is not None:
        log("Configured PostgreSQL is ready.")
        return connection

    url = engine.url
    if not WINDOWS or url.host not in ("localhost", "127.0.0.1"):
        raise RuntimeError("PostgreSQL connection failed. Check the database service and backend/.env.")

    executable = shutil.which("docker")
    if not executable:
        installed = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker/Docker/resources/bin/docker.exe"
        if installed.is_file():
            executable = str(installed)
        else:
            raise RuntimeError("Docker Desktop CLI was not found. Install or open Docker Desktop.")

    def cli(*args):
        if stop():
            raise StartupStopped()
        return docker_cli(root, executable, *args)

    def engine_ready():
        result = cli(*DESKTOP_CONTEXT, "info", "--format", "{{.OSType}}")
        return result.returncode == 0 and result.stdout.strip() == "linux"

    if not engine_ready():
        log(f"Starting Docker Desktop and waiting for its Linux engine (up to {ENGINE_TIMEOUT} seconds).")
        requested = cli("desktop", "start", "--detach")
        if requested.returncode:
            log(f"Docker Desktop start command returned {requested.returncode}; checking engine readiness.")
        if not wait_until(engine_ready, stop, ENGINE_TIMEOUT):
            raise RuntimeError("Docker Desktop Linux engine did not become ready. Open Docker Desktop and check WSL or any startup prompt.")
    log("Docker Desktop Linux engine is ready.")

    compose = (*DESKTOP_CONTEXT, "compose", "--project-directory", str(root))
    listed = cli(*compose, "ps", "--all", "--quiet", "postgres")
    containers = listed.stdout.split()
    if listed.returncode or len(containers) != 1:
        raise RuntimeError("Expected one existing Compose postgres container for this checkout. Check docker compose ps -a and the local Compose configuration.")

    details = cli(*DESKTOP_CONTEXT, "inspect", "--type", "container", containers[0])
    if details.returncode:
        raise RuntimeError("Could not inspect the existing Compose postgres container.")
    try:
        container, = json.loads(details.stdout)
        labels = container["Config"]["Labels"]
        checkout = Path(labels["com.docker.compose.project.working_dir"]).resolve()
    except (ValueError, TypeError, KeyError):
        raise RuntimeError("The existing PostgreSQL container has incomplete Compose metadata.") from None
    if checkout != root.resolve() or labels.get("com.docker.compose.service") != "postgres":
        raise RuntimeError("The PostgreSQL container belongs to a different Compose checkout.")
    bindings = container["HostConfig"]["PortBindings"].get("5432/tcp", [])
    if {"HostIp": "127.0.0.1", "HostPort": str(url.port or 5432)} not in bindings:
        raise RuntimeError("Existing Compose postgres port does not match backend/.env. Check the loopback port mapping.")
    if not any(mount["Destination"] == DATA_PATH and mount["Type"] == "volume" and mount.get("Name")
               for mount in container["Mounts"]):
        raise RuntimeError("Existing Compose postgres container has no named database volume.")

    if not container["State"]["Running"]:
        log(f"Starting this project's existing Compose postgres service on loopback port {url.port or 5432}.")
        started = cli(*compose, "start", "postgres")
        if started.returncode:
            detail = (started.stderr or started.stdout).strip()
            raise RuntimeError(f"Could not start the existing Compose postgres service (exit {started.returncode}). {detail}")
    log(f"Waiting for an authenticated PostgreSQL connection (up to {DATABASE_TIMEOUT} seconds).")
    connection = wait_until(lambda: connect_if_ready(engine), stop, DATABASE_TIMEOUT)
    if connection is None:
        raise RuntimeError("PostgreSQL did not accept the configured connection. Check docker compose ps postgres, docker compose logs postgres, and backend/.env.")
    log("Configured PostgreSQL is ready.")
    return connection
