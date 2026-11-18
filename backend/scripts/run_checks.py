"""Run tests without inheriting developer databases, tokens, or model artifacts."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", default="test*.py", help="Optional unittest discovery pattern")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    with TemporaryDirectory() as directory:
        env = {**os.environ, "DATABASE_URL": "", "API_ACCESS_TOKEN": "", "MODEL_REGISTRY_DIR": "",
               "OPENAI_API_KEY": "", "NVIDIA_API_KEY": "", "OMP_NUM_THREADS": "1",
               "SBI_IMPORT_DIR": "", "SBI_ALERT_RECIPIENTS": "", "SMTP_HOST": "", "SMTP_FROM": "",
               "STOCKAI_RUNTIME_DIR": str(Path(directory) / "runtime"),
               "STOCK_DATA_DB_PATH": str(Path(directory) / "market.db"),
               "TRADING_DB_PATH": str(Path(directory) / "trading.db")}
        return subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "backend/tests", "-p", args.pattern, "-v"],
                              cwd=root, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
