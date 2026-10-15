"""Run tests without inheriting developer databases, tokens, or model artifacts."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


def main():
    root = Path(__file__).resolve().parents[2]
    with TemporaryDirectory() as directory:
        env = {**os.environ, "DATABASE_URL": "", "API_ACCESS_TOKEN": "", "MODEL_REGISTRY_DIR": "",
               "OPENAI_API_KEY": "", "OMP_NUM_THREADS": "1",
               "STOCK_DATA_DB_PATH": str(Path(directory) / "market.db"),
               "TRADING_DB_PATH": str(Path(directory) / "trading.db")}
        return subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "backend/tests", "-v"],
                              cwd=root, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
